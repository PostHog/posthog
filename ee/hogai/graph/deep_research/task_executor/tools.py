import uuid
from collections.abc import Callable
from typing import Optional, cast

import structlog
from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_core.runnables.utils import AddableDict
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph

from posthog.schema import (
    AssistantToolCallMessage,
    HumanMessage,
    ReasoningMessage,
    TaskExecutionItem,
    TaskExecutionStatus,
)

from posthog.exceptions_capture import capture_exception

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.deep_research.task_executor.prompts import AGENT_TASK_PROMPT_TEMPLATE
from ee.hogai.graph.deep_research.types import DeepResearchSingleTaskResult
from ee.hogai.utils.types import AssistantState, VisualizationMessage
from ee.hogai.utils.types.base import (
    AnyAssistantGeneratedQuery,
    AssistantMessageUnion,
    InsightArtifact,
    InsightSearchArtifact,
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


class ExecuteTasksTool:
    """Tool for executing multiple tasks in parallel using the insights subgraph."""

    def __init__(self, insights_subgraph: CompiledStateGraph):
        self._insights_subgraph = insights_subgraph
        self._reasoning_callback: Optional[Callable[[ReasoningMessage], None]] = None
        self._task_progress_callback: Optional[Callable[[str, str | None], None]] = None
        self._task_nodes_seen: dict[str, set[str]] = {}

    def set_reasoning_callback(self, callback: Callable[[ReasoningMessage], None]):
        """Set a callback to emit reasoning messages during task execution."""
        self._reasoning_callback = callback

    def set_task_progress_callback(self, callback: Callable[[str, str | None], None]):
        """Set a callback to emit task-specific progress updates.

        Args:
            callback: Function that takes (task_id, progress_text) parameters
        """
        self._task_progress_callback = callback

    async def astream(
        self,
        input_tuples: list[tuple[TaskExecutionItem, list[InsightArtifact]]],
        config: RunnableConfig,
    ):
        """
        Execute tasks in parallel using insights subgraph and yield results as they complete.
        """

        task_executor = RunnableLambda(self._execute_task_with_insights).with_config(run_name="TaskExecutor")  # type: ignore
        batch_inputs = [{"task": task, "artifacts": artifacts, "config": config} for task, artifacts in input_tuples]

        async for _, output in task_executor.abatch_as_completed(batch_inputs, config=config):
            yield output

        yield ReasoningMessage(
            content=f"All {len(input_tuples)} research tasks completed! Collected insights are ready for synthesis and analysis."
        )

    async def _execute_task_with_insights(self, input_dict: dict) -> DeepResearchSingleTaskResult:
        """Execute a single task using the full insights pipeline."""

        task = input_dict["task"]
        artifacts = input_dict["artifacts"]
        config = input_dict.get("config")

        self._current_task_id = task.id
        self._task_nodes_seen[task.id] = set()

        # This is needed by the InsightsAssistantGraph to return an AssistantToolCallMessage
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
            logger.warning("Task failed: no messages received from insights subgraph", task_id=task.id)
            return self._failed_result(task)

        last_message = subgraph_result_messages[-1]

        if not isinstance(last_message, AssistantToolCallMessage):
            logger.warning(
                "Task failed: last message is not AssistantToolCallMessage",
                task_id=task.id,
            )
            return self._failed_result(task)

        tool_result_message = last_message

        artifacts = self._extract_artifacts(subgraph_result_messages, task)
        if len(artifacts) == 0:
            logger.warning("Task failed: no artifacts extracted", task_id=task.id)
            return self._failed_result(task)

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
        response = await chain.ainvoke(
            {"content": tool_result_message.content},
            config,
        )
        response = cast(LangchainAIMessage, response)
        if self._task_progress_callback:
            self._task_progress_callback(task.id, None)

        return DeepResearchSingleTaskResult(
            id=task.id,
            description=task.description,
            result=str(response),
            artifacts=artifacts,
            status=TaskExecutionStatus.COMPLETED,
        )

    def _failed_result(self, task: TaskExecutionItem) -> DeepResearchSingleTaskResult:
        if self._task_progress_callback:
            self._task_progress_callback(task.id, None)

        return DeepResearchSingleTaskResult(
            id=task.id, description=task.description, result="", artifacts=[], status=TaskExecutionStatus.FAILED
        )

    def _extract_artifacts(
        self, subgraph_result_messages: list[AssistantMessageUnion], task: TaskExecutionItem
    ) -> list[InsightArtifact]:
        """Extract artifacts from insights subgraph execution results."""

        artifacts: list[InsightArtifact] = []
        for message in subgraph_result_messages:
            if isinstance(message, VisualizationMessage) and message.id:
                artifact = InsightArtifact(
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

    def _get_model(self) -> ChatOpenAI:
        return ChatOpenAI(
            model="gpt-4.1",
            temperature=0.3,
        )


class ExecuteNodeTasksTool:
    """Tool for executing multiple tasks in parallel using a single node executor."""

    def __init__(self, node_executor: AssistantNode):
        self._node_executor = node_executor
        self._reasoning_callback: Optional[Callable[[ReasoningMessage], None]] = None
        self._task_progress_callback: Optional[Callable[[str, str | None], None]] = None

    def set_reasoning_callback(self, callback: Callable[[ReasoningMessage], None]):
        """Set a callback to emit reasoning messages during task execution."""
        self._reasoning_callback = callback

    def set_task_progress_callback(self, callback: Callable[[str, str | None], None]):
        """Set a callback to emit task-specific progress updates.

        Args:
            callback: Function that takes (task_id, progress_text) parameters
        """
        self._task_progress_callback = callback

    async def astream(
        self,
        input_tuples: list[tuple[TaskExecutionItem, list[InsightArtifact]]],
        config: RunnableConfig,
    ):
        """
        Execute tasks in parallel using a single node executor and yield results as they complete.
        """

        task_executor = RunnableLambda(self._execute_task_with_node).with_config(run_name="NodeTaskExecutor")  # type: ignore
        batch_inputs = [{"task": task, "artifacts": artifacts, "config": config} for task, artifacts in input_tuples]

        async for _, output in task_executor.abatch_as_completed(batch_inputs, config=config):
            yield output

        yield ReasoningMessage(
            content=f"All {len(input_tuples)} research tasks completed! Collected insights are ready for synthesis and analysis."
        )

    async def _execute_task_with_node(self, input_dict: dict) -> DeepResearchSingleTaskResult:
        """Execute a single task using a single node executor."""

        task = input_dict["task"]
        config = input_dict.get("config")

        task_tool_call_id = f"task_{uuid.uuid4().hex[:8]}"

        formatted_instructions = AGENT_TASK_PROMPT_TEMPLATE.format(
            task_prompt=task.prompt, task_description=task.description
        )

        input_state = AssistantState(
            root_tool_call_id=task_tool_call_id,
            search_insights_query=task.prompt,
        )

        try:
            result = await self._node_executor.arun(input_state, config)

            if not result or not result.messages:
                logger.warning("Task failed: no messages received from node executor", task_id=task.id)
                return self._failed_result(task)

            task_result = result.messages[0].content if result.messages else ""

            # Extract artifacts from the result
            extracted_artifacts = self._extract_artifacts_from_result(result, task)

            if len(extracted_artifacts) == 0:
                logger.warning("Task failed: no artifacts extracted", task_id=task.id)
                return self._failed_result(task)

            # Generate final result using the model
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", formatted_instructions),
                    ("user", "{content}"),
                ]
            )

            model = self._get_model()
            chain = prompt | model
            response = await chain.ainvoke(
                {"content": task_result},
                config,
            )
            response = cast(LangchainAIMessage, response)

            if self._task_progress_callback:
                self._task_progress_callback(task.id, None)

            return DeepResearchSingleTaskResult(
                id=task.id,
                description=task.description,
                result=str(response),
                artifacts=extracted_artifacts,
                status=TaskExecutionStatus.COMPLETED,
            )

        except Exception as e:
            capture_exception(e)
            logger.exception(f"Task failed with exception: {e}", task_id=task.id)
            return self._failed_result(task)

    def _failed_result(self, task: TaskExecutionItem) -> DeepResearchSingleTaskResult:
        if self._task_progress_callback:
            self._task_progress_callback(task.id, None)
        return DeepResearchSingleTaskResult(
            id=task.id, description=task.description, result="", artifacts=[], status=TaskExecutionStatus.FAILED
        )

    def _extract_artifacts_from_result(
        self, result: AssistantState, task: TaskExecutionItem
    ) -> list[InsightSearchArtifact]:
        """Extract artifacts from node execution results."""
        artifacts: list[InsightSearchArtifact] = []
        task_result = result.messages[0].content if result.messages else ""
        if result.insight_ids:
            # For InsightSearchNode, we need to extract insight IDs from the result
            artifact = InsightSearchArtifact(
                id=str(uuid.uuid4()),
                insight_ids=result.insight_ids,
                description=task.prompt,
                selection_reason=task_result,
            )
            artifacts.append(artifact)

        return artifacts

    def _get_model(self) -> ChatOpenAI:
        return ChatOpenAI(
            model="gpt-4.1",
            temperature=0.3,
        )
