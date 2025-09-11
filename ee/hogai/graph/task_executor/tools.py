import uuid
from typing import cast

import structlog
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.utils import AddableDict
from langgraph.graph.state import CompiledStateGraph

from posthog.schema import (
    AssistantMessage,
    AssistantToolCallMessage,
    HumanMessage,
    TaskExecutionItem,
    TaskExecutionStatus,
)

from posthog.exceptions_capture import capture_exception

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.task_executor.base import TaskExecutorTool
from ee.hogai.utils.types import AssistantState, PartialAssistantState, VisualizationMessage
from ee.hogai.utils.types.base import (
    AnyAssistantGeneratedQuery,
    AssistantMessageUnion,
    InsightCreationArtifact,
    InsightCreationTaskExecutionResult,
    InsightSearchArtifact,
    InsightSearchTaskExecutionResult,
)

logger = structlog.get_logger(__name__)

INSIGHT_SUBGRAPH_REASONING_MESSAGES = {
    "query_planner": "Planning query approach...",
    "trends_generator": "Generating trends analysis...",
    "funnel_generator": "Building funnel analysis...",
    "retention_generator": "Analyzing retention patterns...",
    "query_executor": "Executing query...",
    "insight_rag_context": "Searching relevant context...",
}


class SubgraphTaskExecutorTool(TaskExecutorTool[InsightCreationTaskExecutionResult]):
    """
    Task executor tool for compiled subgraphs.
    """

    def __init__(self, subgraph: CompiledStateGraph):
        super().__init__(subgraph)
        self._insights_subgraph = subgraph
        self._task_nodes_seen: dict[str, set[str]] = {}

    async def _execute_single_task(self, input_dict: dict) -> InsightCreationTaskExecutionResult:
        """Execute a single task using a compiled subgraph."""
        from ee.hogai.graph.task_executor.prompts import AGENT_TASK_PROMPT_TEMPLATE

        task = input_dict["task"]
        config = cast(RunnableConfig, input_dict.get("config", RunnableConfig()))

        self._current_task_id = task.id
        self._task_nodes_seen[task.id] = set()

        # Create tool call ID for the subgraph
        task_tool_call_id = f"task_{uuid.uuid4().hex[:8]}"

        formatted_instructions = AGENT_TASK_PROMPT_TEMPLATE.format(
            task_prompt=task.prompt, task_description=task.description
        )

        human_message = HumanMessage(content=formatted_instructions, id=str(uuid.uuid4()))
        input_state = AssistantState(
            messages=[human_message],
            start_id=human_message.id,
            root_tool_call_id=task_tool_call_id,
            root_tool_insight_plan=task.prompt,
        )

        subgraph_result_messages = []
        try:
            async for chunk in self._insights_subgraph.astream(
                input_state, config, subgraphs=True, stream_mode=["updates"]
            ):
                if not chunk:
                    continue
                content = chunk[2]  # type: ignore[index]

                node_name = self._extract_node_name(content)
                self._process_stream_message(node_name, INSIGHT_SUBGRAPH_REASONING_MESSAGES, task.id)

                node_key = next(iter(content))
                if content[node_key]["messages"]:
                    subgraph_result_messages.extend(content[node_key]["messages"])

        except Exception as e:
            capture_exception(e)
            raise

        if len(subgraph_result_messages) == 0 or not subgraph_result_messages[-1]:
            logger.warning("Task failed: no messages received from subgraph", task_id=task.id)
            return self._failed_result(task)

        last_message = subgraph_result_messages[-1]
        if not isinstance(last_message, AssistantToolCallMessage):
            logger.warning(
                "Task failed: last message is not AssistantToolCallMessage",
                task_id=task.id,
            )
            return self._failed_result(task)

        # Extract artifacts and generate final result
        extracted_artifacts = self._extract_artifacts_from_messages(subgraph_result_messages, task)
        if len(extracted_artifacts) == 0:
            logger.warning("Task failed: no artifacts extracted", task_id=task.id)
            return self._failed_result(task)

        final_result = await self._generate_final_result(task, last_message.content, config)

        if self._task_progress_callback:
            self._task_progress_callback(task.id, None)

        return InsightCreationTaskExecutionResult(
            id=task.id,
            description=task.description,
            result=final_result,
            artifacts=extracted_artifacts,
            status=TaskExecutionStatus.COMPLETED,
        )

    def _extract_artifacts_from_messages(
        self, subgraph_result_messages: list[AssistantMessageUnion], task: TaskExecutionItem
    ) -> list[InsightCreationArtifact]:
        """Extract artifacts from subgraph execution results."""
        artifacts: list[InsightCreationArtifact] = []
        for message in subgraph_result_messages:
            if isinstance(message, VisualizationMessage) and message.id:
                artifact = InsightCreationArtifact(
                    id=task.id,
                    description=task.prompt,
                    query=cast(AnyAssistantGeneratedQuery, message.answer),
                )
                artifacts.append(artifact)
        return artifacts

    def _extract_node_name(self, content: AddableDict) -> str | None:
        """Extract the node name from a graph path tuple."""
        node_name = next(iter(content.keys()))
        return str(node_name)

    def _process_stream_message(
        self,
        node_name: str | None,
        node_reasoning_messages: dict[str, str],
        current_task_id: str | None = None,
    ):
        """Process a single message from the stream."""
        if node_name and current_task_id:
            if current_task_id not in self._task_nodes_seen:
                self._task_nodes_seen[current_task_id] = set()

            if node_name not in self._task_nodes_seen[current_task_id]:
                self._task_nodes_seen[current_task_id].add(node_name)

        if self._reasoning_callback:
            if node_name in node_reasoning_messages:
                progress_text = node_reasoning_messages[node_name]
                if self._task_progress_callback and current_task_id:
                    self._task_progress_callback(current_task_id, progress_text)

    def _failed_result(self, task: TaskExecutionItem) -> InsightCreationTaskExecutionResult:
        """Create a failed result for a task."""
        if self._task_progress_callback:
            self._task_progress_callback(task.id, None)

        return InsightCreationTaskExecutionResult(
            id=task.id,
            description=task.description,
            result="Task failed",
            artifacts=[],
            status=TaskExecutionStatus.FAILED,
        )


class NodeTaskExecutorTool(TaskExecutorTool[InsightSearchTaskExecutionResult]):
    """
    Task executor tool for single node execution.
    """

    def __init__(self, node_executor: AssistantNode):
        super().__init__(node_executor)
        self._node_executor = node_executor

    async def _execute_single_task(self, input_dict: dict) -> InsightSearchTaskExecutionResult:
        """Execute a single task using a single node."""

        task = input_dict["task"]
        config = cast(RunnableConfig, input_dict.get("config", RunnableConfig()))

        task_tool_call_id = f"task_{uuid.uuid4().hex[:8]}"

        input_state = AssistantState(
            root_tool_call_id=task_tool_call_id,
            search_insights_query=task.prompt,
        )

        try:
            result = await self._node_executor.arun(input_state, config)

            if not result or not result.messages:
                logger.warning("Task failed: no messages received from node executor", task_id=task.id)
                return self._failed_result(task)

            task_result = (
                result.messages[0].content
                if result.messages and isinstance(result.messages[0], AssistantMessage)
                else ""
            )

            # Extract artifacts from the result
            extracted_artifacts = self._extract_artifacts_from_result(result, task)

            if len(extracted_artifacts) == 0:
                logger.warning("Task failed: no artifacts extracted", task_id=task.id)
                return self._failed_result(task)

            final_result = await self._generate_final_result(task, task_result, config)

            if self._task_progress_callback:
                self._task_progress_callback(task.id, None)

            return InsightSearchTaskExecutionResult(
                id=task.id,
                description=task.description,
                result=final_result,
                artifacts=extracted_artifacts,
                status=TaskExecutionStatus.COMPLETED,
            )

        except Exception as e:
            capture_exception(e)
            logger.exception(f"Task failed with exception: {e}", task_id=task.id)
            return self._failed_result(task)

    def _extract_artifacts_from_result(
        self, result: PartialAssistantState, task: TaskExecutionItem
    ) -> list[InsightSearchArtifact]:
        """Extract artifacts from node execution results."""
        artifacts: list[InsightSearchArtifact] = []
        task_result = (
            result.messages[0].content
            if result.messages and isinstance(result.messages[0], AssistantToolCallMessage)
            else ""
        )

        if result.insight_ids:
            artifact = InsightSearchArtifact(
                id=str(uuid.uuid4()),
                insight_ids=result.insight_ids,
                description=task.prompt,
                selection_reason=task_result,
            )
            artifacts.append(artifact)

        return artifacts

    def _failed_result(self, task: TaskExecutionItem) -> InsightSearchTaskExecutionResult:
        """Create a failed result for a task."""
        if self._task_progress_callback:
            self._task_progress_callback(task.id, None)

        return InsightSearchTaskExecutionResult(
            id=task.id,
            description=task.description,
            result="Task failed",
            artifacts=[],
            status=TaskExecutionStatus.FAILED,
        )
