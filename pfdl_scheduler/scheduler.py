# Copyright The PFDL Contributors
#
# Licensed under the MIT License.
# For details on the licensing terms, see the LICENSE file.
# SPDX-License-Identifier: MIT

"""Contains the Scheduler class."""

# standard libraries
from typing import Any, Callable, Dict, List
import uuid

# local sources
from pfdl_scheduler.model.process import Process
from pfdl_scheduler.model.condition import Condition
from pfdl_scheduler.model.task import Task
from pfdl_scheduler.model.while_loop import WhileLoop
from pfdl_scheduler.model.counting_loop import CountingLoop

from pfdl_scheduler.api.task_api import TaskAPI
from pfdl_scheduler.api.service_api import ServiceAPI

from pfdl_scheduler.utils.parsing_utils import load_file
from pfdl_scheduler.utils.parsing_utils import parse_file

from pfdl_scheduler.petri_net.generator import PetriNetGenerator
from pfdl_scheduler.petri_net.logic import PetriNetLogic

from pfdl_scheduler.scheduling.event import Event
from pfdl_scheduler.scheduling.event import START_PRODUCTION_TASK, SET_PLACE, SERVICE_FINISHED
from pfdl_scheduler.scheduling.task_callbacks import TaskCallbacks

from pfdl_scheduler.utils import helpers


class Scheduler:
    """Schedules Tasks of a given PFDL file.

    The scheduler comprises almost the complete execution of a production order including
    the parsing of the PFDL description, model creation and validation and execution of
    the petri net. It interacts with the execution engines and informs them about services
    or tasks which started or finished.

    Attributes:
        running: A boolean that indicates whether the scheduler is running.
        pfdl_file_valid: A boolean indicating wheter the given PFDL file was valid.
        process: The corresponding Process instance from the PFDL file.
        petri_net_generator: A PetriNetGenerator instance for generating the petri net.
        petri_net_logic: A PetriNetLogic instance for execution of the petri net.
        task_callbacks: TaskCallbacks instance which holds the registered callbacks.
        variable_access_function: The function which will be called when the scheduler needs a variable.
        loop_counters: A dict for mapping task ids to the current loop counter (counting loops).
        awaited_events: A list of awaited `Event`s. Only these events can be passed to the net.
        generate_test_ids: Indicates whether test ids should be generated.
        test_id_counters: A List consisting of counters for the test ids of tasks and services.
    """

    def __init__(
        self, pfdl_file_path: str, generate_test_ids: bool = False, draw_petri_net: bool = True
    ) -> None:
        """Initialize the object.

        If the given path leads to a valid PFDL file the parsing will be started. If no errors
        occour the model of the PFDL File will be transformed into a petri net and be drawn if
        the `draw_petri_net` flag is set. If `generate_test_ids` is set the ids of the called
        tasks and services will be an enumeration starting at 0.

        Args:
            pfdl_file_path: The path to the PFDL file.
            generate_test_ids: A boolean indicating whether test ids should be generated.
            draw_petri_net: A boolean indicating wheter the petri net should be drawn.
        """
        self.running: bool = False
        self.pfdl_file_valid: bool = False
        self.process: Process = None
        self.petri_net_generator: PetriNetGenerator = None
        self.petri_net_logic: PetriNetLogic = None
        self.task_callbacks: TaskCallbacks = TaskCallbacks()
        self.variable_access_function: Callable[[str], str] = None
        self.loop_counters: Dict[str, int] = {}
        self.awaited_events: List[Event] = []
        self.generate_test_ids: bool = generate_test_ids
        self.test_id_counters: List[int] = [0, 0]
        self.pfdl_file_valid, self.process = parse_file(pfdl_file_path)
        if self.pfdl_file_valid:
            self.petri_net_generator = PetriNetGenerator(
                "",
                used_in_extension=False,
                generate_test_ids=generate_test_ids,
                draw_net=draw_petri_net,
            )
            self.register_for_petrinet_callbacks()

            self.petri_net_generator.generate_petri_net(self.process)
            self.petri_net_logic = PetriNetLogic(self.petri_net_generator, draw_petri_net)

        awaited_event = Event(event_type=START_PRODUCTION_TASK, data={})
        self.awaited_events.append(awaited_event)

    def start(self) -> bool:
        """Starts the scheduling process for the given PFDL file from the path.

        Returns:
            True if the corresponding PFDL file was valid and the Scheduler could be started.
        """
        if self.pfdl_file_valid:
            self.fire_event(Event(event_type=START_PRODUCTION_TASK, data={}))
            self.running = True
            return True
        return False

    def fire_event(self, event: Event) -> bool:
        """Forwards the given Event to the PetriNetLogic instance.

        The given `Event` object will be passed to the petri net if it is an awaited
        event.

        Args:
            event: An `Event` instance.

        Returns:
            True if the event could be fired to the petri net (is an awaited event).
        """

        if event in self.awaited_events:
            if self.petri_net_logic.fire_event(event):
                self.awaited_events.remove(event)
                return True
        return False

    def register_callback_task_started(self, callback: Callable[[TaskAPI], Any]) -> bool:
        """Registers the given callback in the task_started list.

        Args:
            callback: Function which will be invoked when a Task is started.

        Returns:
            True if the callback was successfully registered.
        """
        if callback not in self.task_callbacks.task_started:
            self.task_callbacks.task_started.append(callback)
            return True

        print("The given Callback function is already registered!")
        return False

    def register_callback_service_started(self, callback: Callable[[ServiceAPI], Any]) -> bool:
        """Registers the given callback in the service_started list.

        Args:
            callback: Function which will be invoked when a Service is started.

        Returns:
            True if the callback was successfully registered.
        """
        if callback not in self.task_callbacks.service_started:
            self.task_callbacks.service_started.append(callback)
            return True

        print("The given Callback function is already registered!")
        return False

    def register_callback_service_finished(self, callback: Callable[[ServiceAPI], Any]) -> bool:
        """Registers the given callback in the service_finished list.

        Args:
            callback: Function which will be invoked when a Service is finished.

        Returns:
            True if the callback was successfully registered.
        """
        if callback not in self.task_callbacks.service_finished:
            self.task_callbacks.service_finished.append(callback)
            return True

        print("The given Callback function is already registered!")
        return False

    def register_callback_task_finished(self, callback: Callable[[TaskAPI], Any]) -> bool:
        """Registers the given callback in the task_finished list.

        Args:
            callback: Function which will be invoked when a Task is finished.

        Returns:
            True if the callback was successfully registered.
        """
        if callback not in self.task_callbacks.task_finished:
            self.task_callbacks.task_finished.append(callback)
            return True

        print("The given Callback function is already registered!")
        return False

    def register_variable_access_function(self, var_access_func: Callable[[str], str]) -> None:
        """Registers the given callback as the variable acces function of the Scheduler.

        Args:
            var_access_func: The function which will be called when the scheduler needs a variable.
        """
        self.variable_access_function = var_access_func

    def on_task_started(self, task_api: TaskAPI) -> None:
        """Executes Scheduling logic when a Task is started."""
        if self.generate_test_ids:
            task_api.uuid = str(self.test_id_counters[0])
            self.test_id_counters[0] = self.test_id_counters[0] + 1
        else:
            task_api.uuid = str(uuid.uuid4())

        for callback in self.task_callbacks.task_started:
            callback(task_api)

    def on_service_started(self, service_api: ServiceAPI) -> None:
        """Executes Scheduling logic when a Service is started."""
        new_uuid = str(uuid.uuid4())
        if self.generate_test_ids:
            new_uuid = str(self.test_id_counters[1])
            self.test_id_counters[1] = self.test_id_counters[1] + 1
        self.petri_net_generator.place_dict[new_uuid] = self.petri_net_generator.place_dict[
            service_api.uuid
        ]
        service_api.uuid = new_uuid
        awaited_event = Event(event_type=SERVICE_FINISHED, data={"service_id": service_api.uuid})
        self.awaited_events.append(awaited_event)

        for callback in self.task_callbacks.service_started:
            callback(service_api)

    def on_service_finished(self, service_api: ServiceAPI) -> None:
        """Executes Scheduling logic when a Service is finished."""
        for callback in self.task_callbacks.service_finished:
            callback(service_api)

    def on_condition_started(
        self, condition: Condition, then_uuid: str, else_uuid: str, task_context: TaskAPI
    ) -> None:
        """Executes Scheduling logic when a Condition statement is started."""
        if self.check_expression(condition.expression, task_context):
            awaited_event = Event(event_type=SET_PLACE, data={"place_id": then_uuid})
            self.awaited_events.append(awaited_event)
            self.fire_event(awaited_event)
        else:
            awaited_event = Event(event_type=SET_PLACE, data={"place_id": else_uuid})
            self.awaited_events.append(awaited_event)
            self.fire_event(awaited_event)

    def on_while_loop_started(
        self, loop: WhileLoop, then_uuid: str, else_uuid: str, task_context: TaskAPI
    ) -> None:
        """Executes Scheduling logic when a While Loop is started."""
        if self.check_expression(loop.expression, task_context):
            awaited_event = Event(event_type=SET_PLACE, data={"place_id": then_uuid})
            self.awaited_events.append(awaited_event)
            self.fire_event(awaited_event)
        else:
            awaited_event = Event(event_type=SET_PLACE, data={"place_id": else_uuid})
            self.awaited_events.append(awaited_event)
            self.fire_event(awaited_event)

    def on_counting_loop_started(
        self, loop: CountingLoop, then_uuid: str, else_uuid: str, task_context: TaskAPI
    ) -> None:
        """Executes Scheduling logic when a Counting Loop is started."""

        # there can only exist one loop counter per task instance at a time
        loop_counter = self.loop_counters.get(task_context.uuid)
        if loop_counter is None:
            loop_counter = 0
            self.loop_counters[task_context.uuid] = loop_counter
        loop_limit = self.get_loop_limit(loop, task_context)

        if loop_counter < loop_limit:
            awaited_event = Event(event_type=SET_PLACE, data={"place_id": then_uuid})
            self.awaited_events.append(awaited_event)
            self.fire_event(awaited_event)
            self.loop_counters[task_context.uuid] = self.loop_counters[task_context.uuid] + 1
        else:
            awaited_event = Event(event_type=SET_PLACE, data={"place_id": else_uuid})
            self.awaited_events.append(awaited_event)
            self.fire_event(awaited_event)

            # loop is done so reset loop counter for this task context
            self.loop_counters[task_context.uuid] = 0

    def on_parallel_loop_started(
        self,
        loop: CountingLoop,
        task_context: TaskAPI,
        parallelTask: Task,
        parallel_loop_started,
        first_transition_id: str,
        second_transition_id: str,
    ) -> None:
        """Executes Scheduling logic when a Parallel Loop is started."""
        task_count = self.get_loop_limit(loop, task_context)

        # generate parallel tasks in petri net
        self.petri_net_generator.generate_parallel_loop_on_runtime(
            parallelTask,
            task_context,
            task_count,
            parallel_loop_started,
            first_transition_id,
            second_transition_id,
        )

        # start evaluation of net again
        self.petri_net_logic.evaluate_petri_net()

    def get_loop_limit(self, loop: CountingLoop, task_context: TaskAPI) -> int:
        loop_limit = 0
        variable = loop.limit[0]
        loop_limit = self.variable_access_function(variable, task_context)

        for i in range(1, len(loop.limit)):
            loop_limit = loop_limit.attributes[loop.limit[i]]
        return loop_limit

    def on_task_finished(self, task_api: TaskAPI) -> None:
        """Executes Scheduling logic when a Task is finished."""
        for callback in self.task_callbacks.task_finished:
            callback(task_api)
        if task_api.task.name == "productionTask":
            self.running = False

    def register_for_petrinet_callbacks(self) -> None:
        """Register scheduler callback functions in the petri net."""
        callbacks = self.petri_net_generator.callbacks
        callbacks.task_started = self.on_task_started
        callbacks.service_started = self.on_service_started
        callbacks.service_finished = self.on_service_finished
        callbacks.condition_started = self.on_condition_started
        callbacks.while_loop_started = self.on_while_loop_started
        callbacks.counting_loop_started = self.on_counting_loop_started
        callbacks.parallel_loop_started = self.on_parallel_loop_started
        callbacks.task_finished = self.on_task_finished

    def check_expression(self, expression: Dict, task_context: TaskAPI) -> bool:
        """Check the boolean value of the given PFDL expression as a Python expression.

        This method only gets executed if the semantic error check is passed. This means that
        no additional semantic checks has to be performed.

        Arguments:
            expression: A dict representing the expression.
            task_context: The context in which the expression should be evaluated.

        Returns:
            The value of the successfully executed expression in Python as a bool.
        """
        return bool(self.execute_expression(expression, task_context))

    def execute_expression(self, expression: Dict, task_context: TaskAPI) -> Any:
        """Executes the given PFDL expression as a Python expression.

        Arguments:
            expression: A dict representing the expression.
            task_context: The context in which the expression should be evaluated.

        Returns:
            The value of the expression executed in Python (type depends on specific expression).
        """
        if isinstance(expression, (str, int, float, bool)):
            return expression
        if isinstance(expression, list):
            variable_name = expression[0]
            variable = self.variable_access_function(variable_name, task_context)

            for i in range(1, len(expression)):
                variable = variable.attributes[expression[i]]
            return variable
        if len(expression) == 2:
            return not self.execute_expression(expression["value"], task_context)

        if expression["left"] == "(" and expression["right"] == ")":
            return self.execute_expression(expression["binOp"], task_context)

        left_side = self.execute_expression(expression["left"], task_context)
        right_side = self.execute_expression(expression["right"], task_context)

        op_func = helpers.parse_operator(expression["binOp"])
        return op_func(left_side, right_side)
