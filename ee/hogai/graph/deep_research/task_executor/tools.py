from typing import cast
import uuid

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph.state import CompiledStateGraph
import structlog
from langchain_core.runnables import RunnableLambda, RunnableConfig

from ee.hogai.graph.deep_research.types import DeepResearchSingleTaskResult
from ee.hogai.utils.types import (
    AssistantState,
    VisualizationMessage,
)
from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
)
from ee.hogai.utils.types.base import InsightArtifact
from posthog.schema import AssistantToolCallMessage, TaskExecutionItem, TaskExecutionStatus
from ee.hogai.graph.deep_research.task_executor.prompts import AGENT_TASK_PROMPT_TEMPLATE
from langchain_openai import ChatOpenAI

logger = structlog.get_logger(__name__)


class ExecuteTasksTool:
    """Tool for executing multiple tasks in parallel using the insights subgraph."""

    def __init__(self, insights_subgraph: CompiledStateGraph):
        self._insights_subgraph = insights_subgraph

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

    async def _execute_task_with_insights(self, input_dict: dict) -> DeepResearchSingleTaskResult:
        """Execute a single task using the full insights pipeline."""

        task = input_dict["task"]
        artifacts = input_dict["artifacts"]
        config = input_dict.get("config")

        # This is needed by the InsightsAssistantGraph to return an AssistantToolCallMessage
        task_tool_call_id = f"task_{uuid.uuid4().hex[:8]}"

        prompt = (
            task.prompt
            + """

        Previous insights you can use as reference to start:
        """
        )
        for artifact in artifacts:
            prompt += f"- {artifact.id}: {artifact.description}\nQuery: {artifact.query}\n\n"
        prompt = prompt.strip()

        input_state = AssistantState(
            root_tool_call_id=task_tool_call_id,
            root_tool_insight_plan=task.prompt,
        )

        raw_result = await self._insights_subgraph.ainvoke(input_state, config)

        tool_result_message = raw_result["messages"][-1]
        if not isinstance(tool_result_message, AssistantToolCallMessage):
            return self._failed_result(task)

        artifacts = self._extract_artifacts(raw_result, task)
        if len(artifacts) == 0:
            return self._failed_result(task)

        formatted_instructions = AGENT_TASK_PROMPT_TEMPLATE.format(
            task_prompt=task.description, task_instructions=task.prompt
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", formatted_instructions),
                ("user", tool_result_message.content),
            ]
        )

        model = self._get_model()
        chain = prompt | model
        response = await chain.ainvoke(
            {},
            config,
        )
        response = cast(LangchainAIMessage, response)

        return DeepResearchSingleTaskResult(
            description=task.description,
            result=str(response),
            artifacts=artifacts,
            status=TaskExecutionStatus.COMPLETED,
        )

    def _failed_result(self, task: TaskExecutionItem) -> DeepResearchSingleTaskResult:
        return DeepResearchSingleTaskResult(
            description=task.description, result="", artifacts=[], status=TaskExecutionStatus.FAILED
        )

    def _extract_artifacts(self, subgraph_result, task: TaskExecutionItem) -> list[InsightArtifact]:
        """Extract artifacts from insights subgraph execution results."""

        artifacts = []
        messages = subgraph_result["messages"]

        for message in messages:
            if isinstance(message, VisualizationMessage) and message.id:
                artifact = InsightArtifact(
                    id=task.id,
                    description=task.prompt,
                    query=message.answer,
                )
                artifacts.append(artifact)
        return artifacts

    def _get_model(self) -> ChatOpenAI:
        return ChatOpenAI(
            model="gpt-4.1",
            temperature=0.3,
        )
