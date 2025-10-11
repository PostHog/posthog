from pydantic import BaseModel, Field

from posthog.schema import AssistantTool

from ee.hogai.graph.dashboards.nodes import DashboardCreationNode
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types.base import InsightQuery, ToolResult


class CreateDashboardToolArgs(BaseModel):
    search_insights_queries: list[InsightQuery] = Field(
        description="A list of insights to be included in the dashboard. Include all the insights that the user mentioned."
    )
    dashboard_name: str = Field(
        description=(
            "The name of the dashboard to be created based on the user request. It should be short and concise as it will be displayed as a header in the dashboard tile."
        )
    )


class CreateDashboardTool(MaxTool):
    name = AssistantTool.CREATE_DASHBOARD
    description = """
    Use this tool when users ask to create, build, or make a new dashboard with insights.
    This tool will search for existing insights that match the user's requirements so no need to call `search_insights` tool, or create new insights if none are found, then combine them into a dashboard.
    Do not call this tool if the user only asks to find, search for, or look up existing insights and does not ask to create a dashboard.
    If you decided to use this tool, there is no need to call `search_insights` tool beforehand. The tool will search for existing insights that match the user's requirements and create new insights if none are found.
    """
    args_schema = CreateDashboardToolArgs

    async def _arun_impl(self, search_insights_queries: list[InsightQuery], dashboard_name: str) -> ToolResult:
        original_state = self._state
        if self._state:
            self._state = self._state.model_copy(
                update={
                    "dashboard_name": dashboard_name,
                    "search_insights_queries": search_insights_queries,
                    "root_tool_call_id": self._tool_call_id,
                }
            )
        try:
            return await self._run_legacy_node(DashboardCreationNode)
        finally:
            # Restore original state
            self._state = original_state
