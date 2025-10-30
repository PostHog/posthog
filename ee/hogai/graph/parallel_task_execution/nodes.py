import uuid
import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any, Generic, TypeVar, cast

import structlog
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, AssistantToolCall, AssistantToolCallMessage

from posthog.exceptions_capture import capture_exception

from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.types.base import BaseState, BaseStateWithMessages, BaseStateWithTasks, TaskArtifact, TaskResult

logger = structlog.get_logger(__name__)

# Type definitions for task execution
# Each task is represented as a tuple containing:
# 1. The task item with metadata (id, description, status)
# 2. Any input artifacts from previous tasks
# 3. A callable that returns a coroutine to execute the actual task logic
# Note: The callable can return None to indicate a task that produces no result
TaskExecutionCoroutineCallable = Callable[[dict], Coroutine[Any, Any, TaskResult | None]]
TaskExecutionInputTuple = tuple[AssistantToolCall, list[TaskArtifact], TaskExecutionCoroutineCallable]


# Type variables for generic state types
StateT = TypeVar("StateT", bound=BaseState)
PartialStateT = TypeVar("PartialStateT", bound=BaseStateWithTasks)


class BaseTaskExecutorNode(BaseAssistantNode[StateT, PartialStateT], Generic[StateT, PartialStateT]):
    """
    Abstract base class for task execution nodes that handles parallel task execution.

    This node provides a framework for executing multiple tasks concurrently while
    managing their status updates, progress reporting, and result aggregation.

    Key features:
    - Parallel execution of multiple independent tasks
    - Real-time progress updates via reasoning messages or task execution messages
    - Graceful error handling with task isolation (one task failure doesn't affect others)
    - Artifact tracking and dependency management between tasks

    Subclasses must implement:
    - _aget_input_tuples(): Convert state into executable task tuples
    - _aget_final_state(): Aggregate results into final state

    Subclasses can override:
    - arun(): Entry point for task execution
    - _aget_final_state(): Aggregate results into final state

    Attributes:
        _task_execution_message_id: Unique ID for tracking task execution messages
        _reasoning_callback: Callback for sending progress updates
        _send_task_execution_message: Flag to control message type (true for multiple tasks)
    """

    _reasoning_callback: Callable[[str, str | None], Coroutine[Any, Any, None]]

    async def arun(self, state: StateT, config: RunnableConfig) -> PartialStateT:
        if not isinstance(state, BaseStateWithMessages):
            # make mypy happy
            raise ValueError("State is not a BaseStateWithMessages")
        messages = state.messages
        last_message = find_last_message_of_type(messages, AssistantMessage)
        if not last_message or not last_message.tool_calls:
            raise ValueError("No last message found or no tool calls found")
        tool_calls = last_message.tool_calls
        self.dispatcher.message(last_message)
        return await self.aexecute(tool_calls, config)

    async def _aget_input_tuples(self, tool_calls: list[AssistantToolCall]) -> list[TaskExecutionInputTuple]:
        """
        Convert the current state into executable task tuples.
        Must be implemented by subclasses.

        Args:
            tool_calls: The current tool calls containing task definitions

        Returns:
            List of tuples containing (task, artifacts, coroutine) for each task to execute
        """
        raise NotImplementedError

    async def _aget_final_state(self, task_results: list[TaskResult]) -> PartialStateT:
        """
        Aggregate task results into the final state output.
        Must be implemented by subclasses.

        Args:
            tasks: List of executed tasks with updated statuses
            task_results: List of results from task execution

        Returns:
            Partial state containing aggregated results and messages
        """
        # Cast to PartialStateT since we know subclasses will use compatible types
        return cast(
            PartialStateT,
            BaseStateWithTasks(
                task_results=task_results,
            ),
        )

    async def aexecute(self, tool_calls: list[AssistantToolCall], config: RunnableConfig) -> PartialStateT:
        """
        Core execution logic that orchestrates parallel task execution.

        This method:
        1. Retrieves tasks to execute from the tool calls
        2. Sets up progress callbacks based on task count
        3. Executes tasks in parallel
        4. Updates task statuses in real-time
        5. Aggregates results into final state

        Args:
            tool_calls: The current tool calls containing task definitions
            config: Langchain configuration for execution

        Returns:
            Partial state with all task results and messages
        """
        # Get the tasks and their execution coroutines
        input_tuples = await self._aget_input_tuples(tool_calls)
        if len(input_tuples) == 0:
            raise ValueError("No input tuples provided")

        # Execute tasks in parallel and collect results as they complete
        task_results: list[TaskResult] = []
        messages = []
        async for task_id, task_result in self._aexecute_tasks(config, input_tuples):
            task_results.append(task_result)

            message = AssistantToolCallMessage(
                content=task_result.result,
                id=str(uuid.uuid4()),
                tool_call_id=task_id,
            )
            messages.append(message)
            self.dispatcher.message(message)

        # Aggregate all results into the final state
        return await self._aget_final_state(task_results)

    async def _aexecute_tasks(
        self, config: RunnableConfig, input_tuples: list[TaskExecutionInputTuple]
    ) -> AsyncIterator[tuple[str, TaskResult]]:
        """
        Execute multiple tasks in parallel and yield results as they complete.

        This method implements true parallel execution by:
        1. Starting all tasks immediately as asyncio tasks
        2. Yielding results in completion order (fastest task first)
        3. Continuing execution even if individual tasks fail
        4. Canceling remaining tasks if a critical error occurs

        Args:
            config: Langchain configuration for execution
            input_tuples: List of task tuples to execute

        Yields:
            Tuples of (task_id, task_result) as each task completes

        Raises:
            Exception: Re-raises any critical exception after cleaning up running tasks
        """
        try:
            # Start all tasks in parallel immediately
            tasks_with_ids: list[tuple[str, asyncio.Task[TaskResult]]] = []

            for task, artifacts, task_callable in input_tuples:
                # Create input dictionary containing all necessary data for task execution
                input_dict = {
                    "task_id": task.id,
                    "task": task,
                    "artifacts": artifacts,  # Previous tasks' outputs that this task depends on
                    "config": config,
                }

                # Create wrapper coroutine that calls the task callable with the input
                # This closure captures the callable and input_dict for each task
                async def execute_task(callable_func=task_callable, input_data=input_dict):
                    return await callable_func(input_data)

                # Create and start asyncio task immediately - they run concurrently
                async_task = asyncio.create_task(execute_task())
                tasks_with_ids.append((task.id, async_task))

            # Create mapping for tracking pending tasks
            # Maps asyncio.Task -> task_id for result correlation
            pending_tasks = {task: task_id for task_id, task in tasks_with_ids}

            # Yield results as each task completes (in completion order, not submission order)
            while pending_tasks:
                # Wait for ANY task to complete and immediately yield its result
                # This ensures we process results as soon as they're available
                done, _ = await asyncio.wait(pending_tasks.keys(), return_when=asyncio.FIRST_COMPLETED)

                # Process and yield results immediately as they complete
                for completed_task in done:
                    task_id = pending_tasks.pop(completed_task)
                    try:
                        task_result = await completed_task
                        if task_result is not None:
                            yield task_id, task_result
                    except Exception as task_error:
                        # Log the error but continue processing other tasks
                        # This ensures one task failure doesn't stop the entire batch
                        logger.exception(f"Task {task_id} failed", error=str(task_error))
                        continue

        except Exception as e:
            # Critical error occurred - clean up and re-raise
            capture_exception(e)

            # Cancel any remaining running tasks to prevent resource leaks
            for _, async_task in tasks_with_ids:
                if not async_task.done():
                    async_task.cancel()
            raise
