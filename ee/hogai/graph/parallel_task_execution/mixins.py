import uuid
from collections.abc import Sequence
from typing import cast

import structlog
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from posthog.schema import (
    AssistantToolCall,
    AssistantToolCallMessage,
    HumanMessage,
    TaskExecutionStatus,
    VisualizationMessage,
)

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.models.user import User

from ee.hogai.graph.insights.nodes import InsightSearchNode
from ee.hogai.graph.parallel_task_execution.prompts import AGENT_TASK_PROMPT_TEMPLATE
from ee.hogai.utils.dispatcher import AssistantDispatcher
from ee.hogai.utils.helpers import extract_stream_update
from ee.hogai.utils.state import is_value_update
from ee.hogai.utils.types import (
    AnyAssistantGeneratedQuery,
    AssistantMessageUnion,
    AssistantState,
    InsightArtifact,
    PartialAssistantState,
    TaskArtifact,
    TaskResult,
)

logger = structlog.get_logger(__name__)


class WithInsightCreationTaskExecution:
    _team: Team
    _user: User
    _parent_tool_call_id: str | None

    @property
    def dispatcher(self) -> AssistantDispatcher:
        raise NotImplementedError

    async def _execute_create_insight(self, input_dict: dict) -> TaskResult | None:
        """Execute a single task using the full insights pipeline.

        Always returns a TaskResult (even for failures), never None.
        The type allows None for compatibility with the base class.
        """
        # Import here to avoid circular dependency
        from ee.hogai.graph.insights_graph.graph import InsightsGraph

        task = cast(AssistantToolCall, input_dict["task"])
        artifacts = input_dict["artifacts"]
        config = input_dict.get("config")

        self._current_task_id = task.id

        # This is needed by the InsightsGraph to return an AssistantToolCallMessage
        task_tool_call_id = f"task_{uuid.uuid4().hex[:8]}"
        query = task.args["query_description"]

        formatted_instructions = AGENT_TASK_PROMPT_TEMPLATE.format(
            task_prompt=query,
        )

        human_message = HumanMessage(content=formatted_instructions, id=str(uuid.uuid4()))
        input_state = AssistantState(
            messages=[human_message],
            start_id=human_message.id,
            root_tool_call_id=task_tool_call_id,
            root_tool_insight_plan=query,
        )

        subgraph_result_messages: list[AssistantMessageUnion] = []
        assistant_graph = InsightsGraph(
            self._team, self._user, tool_call_id=self._parent_tool_call_id
        ).compile_full_graph()
        try:
            async for chunk in assistant_graph.astream(
                input_state,
                config,
                subgraphs=True,
                stream_mode=["updates"],
            ):
                if not chunk:
                    continue

                update = extract_stream_update(chunk)
                if is_value_update(update):
                    _, content = update
                    node_name = next(iter(content.keys()))
                    messages = content[node_name]["messages"]
                    subgraph_result_messages.extend(messages)
                    for message in messages:
                        self.dispatcher.message(message)

        except Exception as e:
            capture_exception(e)
            raise

        if len(subgraph_result_messages) == 0 or not subgraph_result_messages[-1]:
            logger.warning("Task failed: no messages received from insights subgraph", task_id=task.id)
            return TaskResult(
                id=task.id,
                result="",
                artifacts=[],
                status=TaskExecutionStatus.FAILED,
            )

        last_message = subgraph_result_messages[-1]

        if not isinstance(last_message, AssistantToolCallMessage):
            logger.warning(
                "Task failed: last message is not AssistantToolCallMessage",
                task_id=task.id,
            )
            return TaskResult(
                id=task.id,
                result="",
                artifacts=[],
                status=TaskExecutionStatus.FAILED,
            )

        response = last_message.content

        artifacts = self._extract_artifacts(subgraph_result_messages, task)
        if len(artifacts) == 0:
            response += "\n\nNo artifacts were generated."
            logger.warning("Task failed: no artifacts extracted", task_id=task.id)
            return TaskResult(
                id=task.id,
                result=response,
                artifacts=[],
                status=TaskExecutionStatus.FAILED,
            )

        return TaskResult(
            id=task.id,
            result=response,
            artifacts=artifacts,
            status=TaskExecutionStatus.COMPLETED,
        )

    def _extract_artifacts(
        self, subgraph_result_messages: list[AssistantMessageUnion], tool_call: AssistantToolCall
    ) -> Sequence[InsightArtifact]:
        """Extract artifacts from insights subgraph execution results."""

        artifacts: list[InsightArtifact] = []
        for message in subgraph_result_messages:
            if isinstance(message, VisualizationMessage) and message.id:
                artifact = InsightArtifact(
                    task_id=tool_call.id,
                    id=None,  # The InsightsGraph does not create the insight objects
                    content="",
                    query=cast(AnyAssistantGeneratedQuery, message.answer),
                )
                artifacts.append(artifact)
        return artifacts

    def _get_model(self) -> ChatOpenAI:
        return ChatOpenAI(
            model="gpt-4.1",
            temperature=0.3,
        )


class WithInsightSearchTaskExecution:
    _team: Team
    _user: User
    _parent_tool_call_id: str | None

    @property
    def dispatcher(self) -> AssistantDispatcher:
        raise NotImplementedError

    async def _execute_search_insights(self, input_dict: dict) -> TaskResult:
        """Execute a single task using a single node."""

        task = cast(AssistantToolCall, input_dict["task"])
        config = cast(RunnableConfig, input_dict.get("config", RunnableConfig()))
        query = task.args["search_insights_query"]

        task_tool_call_id = f"task_{uuid.uuid4().hex[:8]}"

        input_state = AssistantState(
            root_tool_call_id=task_tool_call_id,
            search_insights_query=query,
        )

        try:
            result = await InsightSearchNode(self._team, self._user, tool_call_id=self._parent_tool_call_id).arun(
                input_state, config
            )

            if not result or not result.messages:
                logger.warning("Task failed: no messages received from node executor", task_id=task.id)
                return TaskResult(
                    id=task.id,
                    result="",
                    artifacts=[],
                    status=TaskExecutionStatus.FAILED,
                )

            messages = list(result.messages)
            task_result = messages[0].content if messages and isinstance(messages[0], AssistantToolCallMessage) else ""

            # Extract artifacts from the result and messages
            extracted_artifacts = self._extract_artifacts_from_messages(messages, result, task)

            if len(extracted_artifacts) == 0:
                logger.warning("Task failed: no artifacts extracted", task_id=task.id)
                return TaskResult(
                    id=task.id,
                    result="No insights were found.",
                    artifacts=[],
                    status=TaskExecutionStatus.FAILED,
                )

            return TaskResult(
                id=task.id,
                result=task_result,
                artifacts=extracted_artifacts,
                status=TaskExecutionStatus.COMPLETED,
            )

        except Exception as e:
            capture_exception(e)
            logger.exception(f"Task failed with exception: {e}", task_id=task.id)
            return TaskResult(
                id=task.id,
                result="",
                artifacts=[],
                status=TaskExecutionStatus.FAILED,
            )

    def _extract_artifacts_from_messages(
        self, messages: list[AssistantMessageUnion], result: PartialAssistantState, tool_call: AssistantToolCall
    ) -> list[TaskArtifact]:
        """Extract artifacts from captured messages and node result."""
        artifacts: list[TaskArtifact] = []

        # Get content from messages (look for AssistantToolCallMessage)
        content = ""
        for msg in messages:
            if isinstance(msg, AssistantToolCallMessage):
                content = msg.content
                break

        # Create artifacts from selected insight IDs
        if result.selected_insight_ids:
            artifacts.extend(
                [
                    TaskArtifact(
                        task_id=tool_call.id,
                        id=str(insight_id),
                        content=content,
                    )
                    for insight_id in result.selected_insight_ids
                ]
            )

        return artifacts
