from typing import Literal

from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field

from ee.hogai.graph.dashboards.nodes import DashboardCreationNode
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.utils.types.base import AssistantState, InsightQuery, PartialAssistantState

CREATE_DASHBOARD_TOOL_PROMPT = """
Use this tool when users ask to create, build, or make a new dashboard with insights.
This tool will search for existing insights that match the user's requirements so no need to call `search` tool, or create new insights if none are found, then combine them into a dashboard.
Do not call this tool if the user only asks to find, search for, or look up existing insights and does not ask to create a dashboard.
If you decided to use this tool, there is no need to call `search_insights` tool beforehand. The tool will search for existing insights that match the user's requirements and create new insights if none are found.
""".strip()


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
    name: Literal["create_dashboard"] = "create_dashboard"
    description: str = CREATE_DASHBOARD_TOOL_PROMPT
    thinking_message: str = "Creating a dashboard"
    context_prompt_template: str = "Creates a dashboard based on the user's request"
    args_schema: type[BaseModel] = CreateDashboardToolArgs
    show_tool_call_message: bool = False

    async def _arun_impl(
        self, search_insights_queries: list[InsightQuery], dashboard_name: str
    ) -> tuple[str, ToolMessagesArtifact | None]:
        node = DashboardCreationNode(self._team, self._user)
        chain: RunnableLambda[AssistantState, PartialAssistantState | None] = RunnableLambda(node)
        copied_state = self._state.model_copy(
            deep=True,
            update={
                "root_tool_call_id": self.tool_call_id,
                "search_insights_queries": search_insights_queries,
                "dashboard_name": dashboard_name,
            },
        )
        result = await chain.ainvoke(copied_state)
        if not result or not result.messages:
            return "Dashboard creation failed", None
        return "", ToolMessagesArtifact(messages=result.messages)
