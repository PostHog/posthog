from collections.abc import Sequence
from typing import cast

import structlog
from posthoganalytics import capture_exception
from pydantic import BaseModel, Field

from posthog.schema import AssistantMessage, AssistantTool, AssistantToolCallMessage, VisualizationMessage

from ee.hogai.tool import MaxTool
from ee.hogai.utils.helpers import extract_stream_update
from ee.hogai.utils.state import is_task_started_update, is_value_update
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import AnyAssistantGeneratedQuery, AssistantMessageUnion, InsightArtifact, ToolResult

logger = structlog.get_logger(__name__)


class InsightCreationArgs(BaseModel):
    query_description: str = Field(
        description=(
            "A description of the query to generate, encapsulating the details of the user's request. "
            "Include all relevant context from earlier messages too, as the tool won't see that conversation history. "
            "If an existing insight has been used as a starting point, include that insight's filters and query in the description. "
            "Don't be overly prescriptive with event or property names, unless the user indicated they mean this specific name (e.g. with quotes). "
            "If the users seems to ask for a list of entities, rather than a count, state this explicitly."
        )
    )


class CreateInsightTool(MaxTool):
    name = AssistantTool.CREATE_AND_QUERY_INSIGHT.value
    description = """
    Retrieve results for a specific data question by creating a query (aka insight), or iterate on a previous query.
    This tool only retrieves data for a single query at a time.
    """
    args_schema = InsightCreationArgs

    async def _arun_impl(self, query_description: str) -> ToolResult:
        # Import here to avoid circular dependency
        from ee.hogai.graph.graph import InsightsAssistantGraph

        input_state = AssistantState(
            messages=self._state.messages,
            root_tool_call_id=self._tool_call_id,
            root_tool_insight_plan=query_description,
        )

        subgraph_result_messages: list[AssistantMessageUnion] = []
        assistant_graph = InsightsAssistantGraph(self._team, self._user).compile_full_graph()
        try:
            async for chunk in assistant_graph.astream(
                input_state,
                self._config,
                subgraphs=True,
                stream_mode=["updates", "debug"],
            ):
                if not chunk:
                    continue

                update = extract_stream_update(chunk)
                if is_value_update(update):
                    _, content = update
                    node_name = next(iter(content.keys()))
                    messages = content[node_name]["messages"]
                    subgraph_result_messages.extend(messages)
                elif is_task_started_update(update):
                    _, task_update = update
                    node_name = task_update["payload"]["name"]  # type: ignore
                    node_input = task_update["payload"]["input"]  # type: ignore
                    reasoning_message = await assistant_graph.aget_reasoning_message_by_node_name[node_name](
                        node_input, ""
                    )
                    if reasoning_message:
                        progress_text = reasoning_message.content
                        await self._update_tool_call_status(progress_text, reasoning_message.substeps)

        except Exception as e:
            capture_exception(e)
            raise

        if len(subgraph_result_messages) == 0 or not subgraph_result_messages[-1]:
            logger.warning("Task failed: no messages received from insights subgraph", tool_call_id=self._tool_call_id)
            return await self._failed_execution()

        last_message = subgraph_result_messages[-1]

        if not isinstance(last_message, AssistantToolCallMessage):
            logger.warning(
                "Task failed: last message is not AssistantToolCallMessage",
                tool_call_id=self._tool_call_id,
            )
            if isinstance(last_message, AssistantMessage):
                # The agent has requested help from the user
                return await self._successful_execution(last_message.content)
            else:
                return await self._failed_execution()

        response = last_message.content

        artifacts = self._extract_artifacts(query_description, subgraph_result_messages)
        if len(artifacts) == 0:
            response += "\n\nNo artifacts were generated."
            logger.warning("Task failed: no artifacts extracted", tool_call_id=self._tool_call_id)
            return await self._failed_execution()

        return await self._successful_execution(response, artifacts)

    def _extract_artifacts(
        self, query_description: str, subgraph_result_messages: list[AssistantMessageUnion]
    ) -> Sequence[InsightArtifact]:
        """Extract artifacts from insights subgraph execution results."""

        last_message = subgraph_result_messages[-1]
        if not isinstance(last_message, AssistantToolCallMessage):
            return []
        response = last_message.content
        artifacts: list[InsightArtifact] = []
        for message in subgraph_result_messages:
            if isinstance(message, VisualizationMessage) and message.id:
                artifact = InsightArtifact(
                    tool_call_id=self._tool_call_id,
                    id=None,  # The InsightsAssistantGraph does not create the insight objects
                    content=response,
                    plan=query_description,
                    query=cast(AnyAssistantGeneratedQuery, message.answer),
                )
                artifacts.append(artifact)
                break
        return artifacts
