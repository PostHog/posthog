import uuid
import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any, cast

import structlog
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantToolCall, ProgressState, ToolExecution, ToolExecutionMessage, ToolExecutionStatus

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tool import MaxTool
from ee.hogai.tool.base import get_assistant_tool_class
from ee.hogai.utils.types.base import AssistantMessageUnion, ToolResult
from ee.hogai.utils.types.composed import AssistantMaxGraphState

logger = structlog.get_logger(__name__)

ToolExecutionInputTuple = tuple[ToolExecution, MaxTool]


class ParallelToolExecution:
    """
    Abstract base class for parallel tool execution.

    This node provides a framework for executing multiple tools concurrently while
    managing their status updates, progress reporting, and result aggregation.

    Key features:
    - Parallel execution of multiple independent tools
    - Real-time progress updates via reasoning messages or tool execution messages
    - Graceful error handling with tool isolation (one tool failure doesn't affect others)
    - Artifact tracking and dependency management between tools

    Subclasses can override:
    - arun(): Entry point for tool execution

    Attributes:
        _tool_execution_message_id: Unique ID for tracking tool execution messages
        _tool_update_callback: Callback for sending progress updates
        _write_message: Callback for writing messages to the stream
    """

    _team: Team
    _user: User
    _tool_execution_message_id: str
    _tool_update_callback: Callable[[str, str | None, list[str] | None], Coroutine[Any, Any, None]]
    _write_message: Callable[[AssistantMessageUnion], Coroutine[Any, Any, None]]
    _context_manager: AssistantContextManager | None = None

    async def arun(
        self, tool_calls: list[AssistantToolCall], state: AssistantMaxGraphState, config: RunnableConfig
    ) -> tuple[list[ToolResult], ToolExecutionMessage]:
        """
        Main entry point for tool execution. Must be implemented by subclasses.
        Must call self._arun.

        Args:
            input_tuples: The tool input tuples to execute (tool call, tool class)
            config: Langchain configuration for execution, in case the tool needs it

        Returns:
            List of tool results, and the final tool execution message, if any
        """
        return await self._arun(tool_calls, state, config)

    def __init__(
        self, team: Team, user: User, write_message_afunc: Callable[[AssistantMessageUnion], Coroutine[Any, Any, None]]
    ):
        self._team = team
        self._user = user
        self._write_message = write_message_afunc
        # Generate a unique ID for this execution session
        self._tool_execution_message_id = str(uuid.uuid4())

    def _get_context_manager(self, config: RunnableConfig) -> AssistantContextManager:
        if self._context_manager is None:
            self._context_manager = AssistantContextManager(self._team, self._user, config)
        return self._context_manager

    async def _arun(
        self, tool_calls: list[AssistantToolCall], state: AssistantMaxGraphState, config: RunnableConfig
    ) -> tuple[list[ToolResult], ToolExecutionMessage]:
        """
        Core execution logic that orchestrates parallel tool execution.

        This method:
        1. Sets up progress callbacks based on tool count
        2. Executes tools in parallel
        3. Updates tool execution statuses in real-time
        4. Returns the tool results and the final tool execution message

        Args:
            tool_inputs: The tool inputs to execute
            config: Langchain configuration for execution

        Returns:
            List of tool results and the final tool execution message
        """
        if len(tool_calls) == 0:
            raise ValueError("No tool calls provided")

        # Set up the appropriate callback mechanism
        tool_execution_tuples = await self._tool_call_tuples_to_tool_execution_tuples(tool_calls, state, config)
        tool_executions = [tool_execution for tool_execution, _ in tool_execution_tuples]
        self._set_tool_update_callback(tool_executions)

        # Mark all tool execution items as in-progress and send initial status
        for item in tool_executions:
            item.status = ToolExecutionStatus.IN_PROGRESS
        tool_execution_message = await self._asend_tool_execution_message(tool_executions)

        # Execute tool executions in parallel and collect results as they complete
        tool_results: list[ToolResult] = []
        async for tool_id, tool_result in self._aexecute_tools(tool_execution_tuples, state, config):
            tool_results.append(tool_result)
            # Update the status of the completed tool execution item
            for item in tool_executions:
                if item.id != tool_id:
                    continue
                item.status = tool_result.status
                # Send status update after each tool execution item completes
                tool_execution_message = await self._asend_tool_execution_message(tool_executions)
                break

        return tool_results, tool_execution_message

    async def _tool_call_tuples_to_tool_execution_tuples(
        self, tool_calls: list[AssistantToolCall], state: AssistantMaxGraphState, config: RunnableConfig
    ) -> list[ToolExecutionInputTuple]:
        tool_classes = []
        for tool_call in tool_calls:
            tool_class = get_assistant_tool_class(tool_call.name)
            if tool_class is None:
                # Ignoring a tool that the backend doesn't know about - might be a deployment mismatch
                continue
            tool_classes.append(tool_class)
        tool_classes_map = {
            ToolClass.name: ToolClass
            for ToolClass in await asyncio.gather(
                *[
                    tool.create_tool_class(
                        team=self._team,
                        user=self._user,
                        state=state,
                        config=config,
                        context_manager=self._get_context_manager(config),
                    )
                    for tool in tool_classes
                ]
            )
        }
        tool_execution_tuples = []
        for tool_call in tool_calls:
            ToolClass = tool_classes_map[tool_call.name]
            args: dict[str, Any] = (
                (ToolClass.tool_function_description.model_validate(tool_call.args)).model_dump()
                if ToolClass.args_schema
                else {}
            )
            tool_call_id = cast(str, tool_call.id)
            tool_name = ToolClass.name
            tool_execution = ToolExecution(
                id=tool_call_id,
                description=tool_call.args.get("tool_call_explanation", tool_call.name),
                args=args,
                status=ToolExecutionStatus.IN_PROGRESS,
                tool_name=tool_name,  # create_insight
            )
            tool_execution_tuples.append((tool_execution, ToolClass))
        return tool_execution_tuples

    def _set_tool_update_callback(self, items: list[ToolExecution]):
        """
        Set up a callback function for progress updates during tool execution.

        Args:
            tool_executions: List of tool execution items that will be executed
        """

        async def callback(id: str, content: str | None, substeps: list[str] | None = None):
            # Find the tool execution item and update its progress
            for tool_execution in items:
                if tool_execution.id == id:
                    if content is None:
                        tool_execution.progress = None
                    else:
                        tool_execution.progress = ProgressState(content=content, substeps=substeps)
                    await self._asend_tool_execution_message(items)

        self._tool_execution_update_callback = callback

    async def _aexecute_tools(
        self,
        input_tuples: list[ToolExecutionInputTuple],
        state: AssistantMaxGraphState,
        config: RunnableConfig,
    ) -> AsyncIterator[tuple[str, ToolResult]]:
        """
        Execute multiple tools in parallel and yield results as they complete.

        This method implements true parallel execution by:
        1. Starting all tool executions immediately as asyncio tasks
        2. Yielding results in completion order (fastest task first)
        3. Continuing execution even if individual tasks fail
        4. Canceling remaining tasks if a critical error occurs

        Args:
            config: Langchain configuration for execution
            input_tuples: List of tool execution tuples to execute

        Yields:
            Tuples of (tool_execution_id, tool_result) as each tool execution item completes

        Raises:
            Exception: Re-raises any critical exception after cleaning up running tasks
        """
        try:
            # Start all tasks in parallel immediately
            tasks_with_ids: list[tuple[str, asyncio.Task[ToolResult | None]]] = []

            for tool_execution, tool_execution_class in input_tuples:
                # Create input dictionary containing all necessary data for task execution

                # Create wrapper coroutine that calls the tool execution callable with the input
                # This closure captures the callable and input for each tool execution
                async def execute_tool(
                    tool_execution_class=tool_execution_class, input=tool_execution
                ) -> ToolResult | None:
                    return await tool_execution_class.arun(
                        input.id, input.args, tool_update_callback=self._tool_execution_update_callback
                    )

                # Create and start asyncio task immediately - they run concurrently
                async_task = asyncio.create_task(execute_tool())
                tasks_with_ids.append((tool_execution.id, async_task))

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
                        tool_result = await completed_task
                        if tool_result is None:
                            tool_execution = next(
                                tool_execution for tool_execution, _ in input_tuples if tool_execution.id == task_id
                            )
                            yield task_id, await self._failed_result(tool_execution)
                        else:
                            yield task_id, tool_result
                    except Exception as task_error:
                        # Log the error but continue processing other tasks
                        # This ensures one task failure doesn't stop the entire batch
                        logger.exception(f"Tool execution with id {task_id} failed", error=str(task_error))
                        continue

        except Exception as e:
            # Critical error occurred - clean up and re-raise
            capture_exception(e)

            # Cancel any remaining running tasks to prevent resource leaks
            for _, async_task in tasks_with_ids:
                if not async_task.done():
                    async_task.cancel()
            raise

    def _get_tool_execution_message(self, item: list[ToolExecution]) -> ToolExecutionMessage:
        # Create a message containing all tool execution items with their current status
        # Use copy() to avoid mutations affecting the message
        return ToolExecutionMessage(tool_executions=item.copy())

    async def _asend_tool_execution_message(self, items: list[ToolExecution]) -> ToolExecutionMessage:
        """
        Send a tool execution message to update the UI with current tool execution item statuses.

        This is only sent when executing multiple tools (not for single tool execution).
        The message contains all tool execution items with their current status and progress.

        Args:
            tool_executions: List of tool execution items with their current status and progress
        """
        is_in_progress = any(item.status == ToolExecutionStatus.IN_PROGRESS for item in items)
        tool_execution_message = self._get_tool_execution_message(items)
        if not is_in_progress:
            tool_execution_message.id = self._tool_execution_message_id
        await self._write_message(tool_execution_message)
        return tool_execution_message

    async def _failed_result(self, item: ToolExecution) -> ToolResult:
        await self._tool_execution_update_callback(item.id, None, None)
        return ToolResult(
            id=item.id,
            content="",
            artifacts=[],
            status=ToolExecutionStatus.FAILED,
            tool_name=item.tool_name,
            send_result_to_frontend=False,
        )
