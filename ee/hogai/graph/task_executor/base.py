import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Generic, Optional, TypeVar, Union, cast

import structlog
from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_openai import ChatOpenAI
from langgraph.config import get_stream_writer
from langgraph.graph.state import CompiledStateGraph

from posthog.schema import (
    AssistantMessage,
    ReasoningMessage,
    TaskExecutionItem,
    TaskExecutionMessage,
    TaskExecutionStatus,
)

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from ee.hogai.graph.base import AssistantNode, BaseAssistantNode
from ee.hogai.graph.deep_research.types import DeepResearchNodeName
from ee.hogai.graph.taxonomy.types import TaxonomyNodeName
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.types.base import AssistantNodeName, BaseTaskExecutionState, InsightArtifact, TaskExecutionResult

logger = structlog.get_logger(__name__)

TaskExecutionStateType = TypeVar("TaskExecutionStateType", bound="BaseTaskExecutionState")
PartialTaskExecutionStateType = TypeVar("PartialTaskExecutionStateType", bound="BaseTaskExecutionState")
TaskResultType = TypeVar("TaskResultType", bound=TaskExecutionResult)


class TaskExecutorTool(ABC, Generic[TaskResultType]):
    """
    Abstract base class for task execution tools.
    """

    def __init__(self, executor: Union[CompiledStateGraph, AssistantNode]):
        self._executor = executor
        self._reasoning_callback: Optional[Callable[[ReasoningMessage], None]] = None
        self._task_progress_callback: Optional[Callable[[str, str | None], None]] = None

    def set_reasoning_callback(self, callback: Callable[[ReasoningMessage], None]):
        """Set a callback to emit reasoning messages during task execution."""
        self._reasoning_callback = callback

    def set_task_progress_callback(self, callback: Callable[[str, str | None], None]):
        """Set a callback to emit task-specific progress updates."""
        self._task_progress_callback = callback

    async def astream(
        self,
        input_tuples: list[tuple[Any, list[InsightArtifact]]],
        config: RunnableConfig,
    ):
        """Execute tasks in parallel and yield results as they complete."""
        task_executor = RunnableLambda(self._execute_single_task).with_config(run_name="TaskExecutor")  # type: ignore
        batch_inputs = [{"task": task, "artifacts": artifacts, "config": config} for task, artifacts in input_tuples]

        async for _, output in task_executor.abatch_as_completed(batch_inputs, config=config):
            yield output

        yield ReasoningMessage(content=f"All {len(input_tuples)} tasks completed! Results are ready for processing.")

    @abstractmethod
    async def _execute_single_task(self, input_dict: dict) -> TaskResultType:
        """Execute a single task and return the result."""
        pass

    def _get_model(self) -> ChatOpenAI:
        return ChatOpenAI(
            model="gpt-4.1",
            temperature=0.3,
        )

    async def _generate_final_result(self, task: TaskExecutionItem, content: str, config: RunnableConfig) -> str:
        """Generate the final result using the model."""
        from ee.hogai.graph.task_executor.prompts import AGENT_TASK_PROMPT_TEMPLATE

        formatted_instructions = AGENT_TASK_PROMPT_TEMPLATE.format(
            task_prompt=task.prompt, task_description=task.description
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", formatted_instructions),
                ("user", "{content}"),
            ]
        )

        model = self._get_model()
        chain = prompt | model
        response = await chain.ainvoke({"content": content}, config)
        response = cast(LangchainAIMessage, response)

        return str(response)


class GenericTaskExecutorNode(
    BaseAssistantNode[TaskExecutionStateType, PartialTaskExecutionStateType],
    Generic[TaskExecutionStateType, PartialTaskExecutionStateType, TaskResultType],
):
    """
    Generic task executor node that can be used across different graph types.
    """

    def __init__(
        self,
        team: Team,
        user: User,
        executor: Union[CompiledStateGraph, AssistantNode],
    ):
        super().__init__(team, user)
        self._execute_tasks_tool = self._create_task_executor_tool(executor)

    @abstractmethod
    def _create_task_executor_tool(
        self, executor: Union[CompiledStateGraph, AssistantNode]
    ) -> TaskExecutorTool[TaskResultType]:
        """Create the appropriate task executor tool based on the executor type."""
        pass

    @abstractmethod
    def _get_node_name(self) -> AssistantNodeName | TaxonomyNodeName | DeepResearchNodeName:
        """Get the node name for this executor."""
        pass

    async def arun(self, state: TaskExecutionStateType, config: RunnableConfig) -> PartialTaskExecutionStateType | None:
        """Execute tasks from the state."""
        last_tool_call_message = find_last_message_of_type(state.messages, AssistantMessage)
        if not (last_tool_call_message and last_tool_call_message.tool_calls):
            raise ValueError("No tool call message found")

        tool_call_id = last_tool_call_message.tool_calls[0].id
        if not state.tasks:
            logger.warning("No tasks provided to execute")
            return self._create_empty_response(tool_call_id)

        return await self._execute_tasks(state, config, tool_call_id)

    async def _execute_tasks(
        self, state: TaskExecutionStateType, config: RunnableConfig, tool_call_id: str
    ) -> PartialTaskExecutionStateType:
        """Execute all tasks in the state."""
        try:
            writer = get_stream_writer()

            # Collect existing artifacts
            artifacts: list[InsightArtifact] = []
            for task_result in state.task_results:
                artifacts.extend(task_result.artifacts)

            if not state.tasks:
                raise ValueError("No tasks to execute")

            tasks = state.tasks.copy()
            input_tuples = []
            for task in tasks:
                task.status = TaskExecutionStatus.IN_PROGRESS
                task_artifacts = []
                if hasattr(task, "artifact_ids") and task.artifact_ids:
                    task_artifacts = [artifact for artifact in artifacts if artifact.id in task.artifact_ids]
                input_tuples.append((task, task_artifacts))

            # Send initial message showing all tasks as pending
            task_execution_message_id = str(uuid.uuid4())
            initial_message = TaskExecutionMessage(id=task_execution_message_id, tasks=tasks)
            writer(self._message_to_langgraph_update(initial_message, self._get_node_name()))

            # Set up callbacks
            def emit_reasoning(reasoning_msg: ReasoningMessage):
                writer(self._message_to_langgraph_update(reasoning_msg, self._get_node_name()))

            def emit_task_progress(task_id: str, progress_text: str | None):
                for task in tasks:
                    if task.id == task_id:
                        task.progress_text = progress_text
                        updated_message = TaskExecutionMessage(id=task_execution_message_id, tasks=tasks)
                        writer(self._message_to_langgraph_update(updated_message, self._get_node_name()))
                        break

            self._execute_tasks_tool.set_reasoning_callback(emit_reasoning)
            self._execute_tasks_tool.set_task_progress_callback(emit_task_progress)

            # Execute tasks
            task_results = []
            async for stream_item in self._execute_tasks_tool.astream(input_tuples, config):
                if isinstance(stream_item, ReasoningMessage):
                    writer(self._message_to_langgraph_update(stream_item, self._get_node_name()))
                elif isinstance(stream_item, TaskExecutionResult):
                    task_result = cast(TaskResultType, stream_item)
                    for task in tasks:
                        if task.id == task_result.id:
                            task.status = task_result.status
                            if task_result.artifacts:
                                task.artifact_ids = [artifact.id for artifact in task_result.artifacts]
                            break

                    completed_message = TaskExecutionMessage(id=task_execution_message_id, tasks=tasks.copy())
                    writer(self._message_to_langgraph_update(completed_message, self._get_node_name()))
                    task_results.append(task_result)

            # Create final response
            return self._create_final_response(task_results, tool_call_id, task_execution_message_id, tasks)

        except Exception as e:
            capture_exception(e)
            logger.exception(f"Error in {self.__class__.__name__}: {e}", exc_info=True)
            raise

    @abstractmethod
    def _create_final_response(
        self, task_results: list[TaskResultType], tool_call_id: str, task_execution_message_id: str, tasks: list[Any]
    ) -> PartialTaskExecutionStateType:
        """Create the final response after task execution."""
        pass

    @abstractmethod
    def _create_empty_response(self, tool_call_id: str) -> PartialTaskExecutionStateType:
        """Create an empty response when no tasks are provided."""
        pass
