import structlog
from pydantic import BaseModel, Field

from posthog.schema import AssistantTool, AssistantToolCallMessage

from ee.hogai.graph.dashboards.nodes import DashboardCreationNode
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types.base import AssistantState, InsightQuery, ToolResult

logger = structlog.get_logger(__name__)


class DashboardCreationArgs(BaseModel):
    search_insights_queries: list[InsightQuery] = Field(
        description="A list of insights to be included in the dashboard. Include all the insights that the user mentioned."
    )
    dashboard_name: str = Field(
        description=(
            "The name of the dashboard to be created based on the user request. It should be short and concise as it will be displayed as a header in the dashboard tile."
        )
    )


class CreateDashboardTool(MaxTool):
    name = AssistantTool.CREATE_DASHBOARD.value
    description = """
    Create a dashboard with insights based on the user's request.
    Use this tool when users ask to create, build, or make a new dashboard with insights.
    This tool will search for existing insights that match the user's requirements so no need to call `search_insights` tool.
    or create new insights if none are found, then combine them into a dashboard.
    Do not call this tool if the user only asks to find, search for, or look up existing insights and does not ask to create a dashboard.
    If you decided to use this tool, there is no need to call `search_insights` tool beforehand. The tool will search for existing insights that match the user's requirements and create new insights if none are found.
    """
    args_schema = DashboardCreationArgs

    async def _arun_impl(self, search_insights_queries: list[InsightQuery], dashboard_name: str) -> ToolResult:
        state = AssistantState(
            root_tool_call_id=self._tool_call_id,
            search_insights_queries=search_insights_queries,
            dashboard_name=dashboard_name,
        )
        node = DashboardCreationNode(team=self._team, user=self._user)
        result = await node.arun(state, self._config)
        if not result or not result.messages:
            logger.warning("Task failed: no messages received from node executor", tool_call_id=self._tool_call_id)
            return await self._failed_execution()
        last_message = result.messages[-1]
        if not isinstance(last_message, AssistantToolCallMessage):
            logger.warning("Task failed: last message is not AssistantToolCallMessage", tool_call_id=self._tool_call_id)
            return await self._failed_execution()
        return await self._successful_execution(last_message.content, [])
