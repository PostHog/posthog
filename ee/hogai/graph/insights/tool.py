from collections.abc import Sequence

import structlog
from pydantic import BaseModel, Field

from posthog.schema import AssistantMessage, AssistantTool, AssistantToolCallMessage

from posthog.exceptions_capture import capture_exception

from ee.hogai.graph.insights.nodes import InsightSearchNode
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types import AssistantState, PartialAssistantState, ToolResult
from ee.hogai.utils.types.base import InsightArtifact

logger = structlog.get_logger(__name__)


class SearchInsightsToolArgs(BaseModel):
    search_query: str = Field(
        description="The user's query to search for insights. "
        "Include all relevant context from earlier messages too, as the tool won't see that conversation history."
    )


class SearchInsightsTool(MaxTool):
    name = AssistantTool.SEARCH_INSIGHTS.value
    description = """
    Search through existing insights to find matches based on the user's query.
    Use this tool when users ask to find, search for, or look up existing insights.
    IMPORTANT: NEVER CALL THIS TOOL IF THE USER ASKS TO CREATE A DASHBOARD.
    Only use this tool when users ask to find, search for, or look up insights.
    If the user asks to create a dashboard, use the `create_dashboard` tool instead.
    """
    thinking_message = "Searching insights"
    args_schema = SearchInsightsToolArgs

    async def _arun_impl(self, search_query: str) -> ToolResult:
        input_state = AssistantState(
            root_tool_call_id=self._tool_call_id,
            search_insights_query=search_query,
        )

        try:
            result = await InsightSearchNode(team=self._team, user=self._user).arun(input_state, self._config)

            if not result or not result.messages:
                logger.warning("Task failed: no messages received from node executor", tool_call_id=self._tool_call_id)
                return await self._failed_execution()

            task_result = (
                result.messages[0].content
                if result.messages and isinstance(result.messages[0], AssistantMessage)
                else ""
            )

            # Extract artifacts from the result
            extracted_artifacts = self._extract_artifacts_from_result(result)

            if len(extracted_artifacts) == 0:
                logger.warning("Task failed: no artifacts extracted", tool_call_id=self._tool_call_id)
                return await self._failed_execution()

            await self._update_tool_call_status(None)

            return await self._successful_execution(task_result, extracted_artifacts)

        except Exception as e:
            capture_exception(e)
            logger.exception(f"Task failed with exception: {e}", tool_call_id=self._tool_call_id)
            return await self._failed_execution()

    def _extract_artifacts_from_result(self, result: PartialAssistantState) -> Sequence[InsightArtifact]:
        """Extract artifacts from node execution results."""
        artifacts: Sequence[InsightArtifact] = []
        content = (
            result.messages[0].content
            if result.messages and isinstance(result.messages[0], AssistantToolCallMessage)
            else ""
        )

        if result.selected_insight_ids:
            artifacts.extend(
                [
                    InsightArtifact(
                        tool_call_id=self._tool_call_id,
                        id=str(insight_id),
                        content=content,
                    )
                    for insight_id in result.selected_insight_ids
                ]
            )

        return artifacts
