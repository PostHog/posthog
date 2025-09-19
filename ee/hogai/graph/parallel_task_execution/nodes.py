import uuid
import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any, Generic, TypeVar, cast

import structlog
from langchain_core.runnables import RunnableConfig

from posthog.schema import TaskExecutionItem, TaskExecutionMessage, TaskExecutionStatus

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.utils.types.base import BaseStateWithTasks, TaskArtifact, TaskResult

logger = structlog.get_logger(__name__)

# Type definitions for task execution
# Each task is represented as a tuple containing:
# 1. The task item with metadata (id, description, status)
# 2. Any input artifacts from previous tasks
# 3. A callable that returns a coroutine to execute the actual task logic
# Note: The callable can return None to indicate a task that produces no result
TaskExecutionCoroutineCallable = Callable[[dict], Coroutine[Any, Any, TaskResult | None]]
TaskExecutionInputTuple = tuple[TaskExecutionItem, list[TaskArtifact], TaskExecutionCoroutineCallable]


# Type variables for generic state types
StateT = TypeVar("StateT", bound=BaseStateWithTasks)
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

    _task_execution_message_id: str
    _reasoning_callback: Callable[[str, str | None], Coroutine[Any, Any, None]]
    _send_task_execution_message: bool

    def __init__(self, team: Team, user: User):
        super().__init__(team, user)
        # Generate a unique ID for this execution session
        self._task_execution_message_id = str(uuid.uuid4())

    async def arun(self, state: StateT, config: RunnableConfig) -> PartialStateT:
        """
        Main entry point for task execution. Must be implemented by subclasses.
        Must call self._arun.

        Args:
            state: The current state containing task definitions
            config: Langchain configuration for execution

        Returns:
            Partial state with execution results
        """
        return await self._arun(state, config)

    async def _aget_input_tuples(self, state: StateT) -> list[TaskExecutionInputTuple]:
        """
        Convert the current state into executable task tuples.
        Must be implemented by subclasses.

        Args:
            state: The current state containing task definitions

        Returns:
            List of tuples containing (task, artifacts, coroutine) for each task to execute
        """
        raise NotImplementedError

    async def _aget_final_state(self, tasks: list[TaskExecutionItem], task_results: list[TaskResult]) -> PartialStateT:
        """
        Aggregate task results into the final state output.
        Must be implemented by subclasses.

        Args:
            tasks: List of executed tasks with updated statuses
            task_results: List of results from task execution

        Returns:
            Partial state containing aggregated results and messages
        """
        await self._asend_task_execution_message(tasks)
        # Cast to PartialStateT since we know subclasses will use compatible types
        return cast(
            PartialStateT,
            BaseStateWithTasks(
                task_results=task_results,
                tasks=tasks,
            ),
        )

    async def _arun(self, state: StateT, config: RunnableConfig) -> PartialStateT:
        """
        Core execution logic that orchestrates parallel task execution.

        This method:
        1. Retrieves tasks to execute from the state
        2. Sets up progress callbacks based on task count
        3. Executes tasks in parallel
        4. Updates task statuses in real-time
        5. Aggregates results into final state

        Args:
            state: The current state containing task definitions
            config: Langchain configuration for execution

        Returns:
            Partial state with all task results and messages
        """
        # Get the tasks and their execution coroutines
        input_tuples = await self._aget_input_tuples(state)
        if len(input_tuples) == 0:
            raise ValueError("No input tuples provided")

        tasks = [task for task, _, _ in input_tuples]

        # Set up the appropriate callback mechanism
        self.set_reasoning_callback(tasks)
        # Use TaskExecutionMessage for multiple tasks, ReasoningMessage for single task
        self._send_task_execution_message = len(input_tuples) > 1

        # Mark all tasks as in-progress and send initial status
        for task in tasks:
            task.status = TaskExecutionStatus.IN_PROGRESS
        await self._asend_task_execution_message(tasks)

        # Execute tasks in parallel and collect results as they complete
        task_results: list[TaskResult] = []
        async for task_id, task_result in self._aexecute_tasks(config, input_tuples):
            task_results.append(task_result)

            # Update the status of the completed task
            for task in tasks:
                if task.id != task_id:
                    continue
                task.status = task_result.status
                if task_result.artifacts:
                    task.artifact_ids = [artifact.task_id for artifact in task_result.artifacts]
                # Send status update after each task completes
                await self._asend_task_execution_message(tasks)
                break

        # Send final status message
        await self._asend_task_execution_message(tasks)

        # Aggregate all results into the final state
        return await self._aget_final_state(tasks, task_results)

    def set_reasoning_callback(self, tasks: list[TaskExecutionItem]):
        """
        Set up a callback function for progress updates during task execution.

        The callback behavior depends on the number of tasks:
        - Single task: Progress is sent as ReasoningMessage
        - Multiple tasks: Progress updates the task's progress_text field in TaskExecutionMessage

        Args:
            tasks: List of tasks that will be executed
        """

        async def callback(task_id: str, progress_text: str | None):
            # Skip if there's no progress text for single-task execution
            if not self._send_task_execution_message and progress_text is None:
                return

            # Find the task and update its progress
            for task in tasks:
                if task.id == task_id:
                    if self._send_task_execution_message:
                        # For multiple tasks, update the task's progress text
                        task.progress_text = progress_text
                        await self._asend_task_execution_message(tasks)
                    elif progress_text:
                        # For single task, send detailed reasoning message
                        await self._write_reasoning(content=progress_text)
                    break

        self._reasoning_callback = callback

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

    async def _asend_task_execution_message(self, tasks: list[TaskExecutionItem]) -> None:
        """
        Send a task execution message to update the UI with current task statuses.

        This is only sent when executing multiple tasks (not for single task execution).
        The message contains all tasks with their current status and progress.

        Args:
            tasks: List of tasks with their current status and progress
        """
        # Only send task execution messages for multiple-task scenarios
        if not self._send_task_execution_message:
            return

        # Create a message containing all tasks with their current status
        # Use copy() to avoid mutations affecting the message
        task_execution_message = TaskExecutionMessage(id=self._task_execution_message_id, tasks=tasks.copy())
        await self._write_message(task_execution_message)

    async def _failed_result(self, task: TaskExecutionItem) -> TaskResult:
        await self._reasoning_callback(task.id, None)
        return TaskResult(
            id=task.id, description=task.description, result="", artifacts=[], status=TaskExecutionStatus.FAILED
        )
