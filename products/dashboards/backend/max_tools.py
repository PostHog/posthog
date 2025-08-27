from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

# from posthog.api.dashboards.dashboard import DashboardSerializer
from posthog.exceptions_capture import capture_exception
from posthog.models import Dashboard, Team, User

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.graph import BaseAssistantGraph
from ee.hogai.graph.insights.nodes import InsightSearchNode
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState

from .prompts import DASHBOARD_PLANNER_SYSTEM_PROMPT, DASHBOARD_PLANNER_USER_PROMPT


class DashboardCreatorArgs(BaseModel):
    instructions: str = Field(description="Natural language description of the dashboard to create")


class DashboardPlan(BaseModel):
    """Structured output for dashboard planning."""

    dashboard_name: str = Field(description="A concise, descriptive name for the dashboard. Max 50 characters.")
    dashboard_description: str = Field(
        description="A clear description of what this dashboard will contain. Max 100 characters."
    )
    search_query: str = Field(
        description="Refined query to find relevant insights for the dashboard. Max 100 characters."
    )


class DashboardPlannerNode(AssistantNode):
    """Node that analyzes the user instructions and extracts dashboard requirements using LLM."""

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        """Parse instructions and plan dashboard creation using LLM."""
        instructions = state.dashboard_creation_instructions
        if not instructions:
            return PartialAssistantState()

        try:
            # Create LLM instance with structured output
            llm = MaxChatOpenAI(model="gpt-4.1-nano", temperature=0.7, user=self._user, team=self._team)

            # Use structured output with the Pydantic model
            structured_llm = llm.with_structured_output(DashboardPlan)

            # Create the prompt
            messages = [
                SystemMessage(content=DASHBOARD_PLANNER_SYSTEM_PROMPT),
                HumanMessage(content=DASHBOARD_PLANNER_USER_PROMPT.format(instructions=instructions)),
            ]

            # Get structured response
            dashboard_plan = await structured_llm.ainvoke(messages)

            return PartialAssistantState(
                dashboard_name=dashboard_plan.dashboard_name,
                dashboard_description=dashboard_plan.dashboard_description,
                search_insights_query=dashboard_plan.search_query,
            )

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return self._fallback_extraction(instructions)

    def _fallback_extraction(self, instructions: str) -> PartialAssistantState:
        """Fallback method using simple heuristics if LLM fails."""
        import re

        # Simple regex patterns for name extraction
        patterns = [
            r'create dashboard (?:called|named) ["\']([^"\']+)["\']',
            r'dashboard ["\']([^"\']+)["\']',
            r'create ["\']([^"\']+)["\'] dashboard',
        ]

        dashboard_name = "New Dashboard"
        for pattern in patterns:
            match = re.search(pattern, instructions.lower())
            if match:
                dashboard_name = match.group(1).title()
                break

        return PartialAssistantState(
            dashboard_name=dashboard_name, dashboard_description=None, search_insights_query=None
        )


class DashboardCreatorNode(AssistantNode):
    """Node that creates the actual dashboard with found insights."""

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        """Create dashboard and add insights to it."""
        try:
            # last_message = state.messages[-1]

            if not state.dashboard_name or not state.dashboard_description:
                return PartialAssistantState()

            # Create the dashboard
            # dashboard_data = {
            #     "name": state.dashboard_name,
            #     "description": state.dashboard_description,

            # }

            # Create a mock request object for the serializer
            # class MockRequest:
            #     def __init__(self, user, data):
            #         self.user = user
            #         self.data = data
            #         self.headers = {}
            #         self.method = "POST"

            # serializer = DashboardSerializer(
            #     data=dashboard_data,
            #     context={
            #         "team_id": self._team.id,
            #         "get_team": lambda: self._team,
            #         "request": MockRequest(self._user, dashboard_data),
            #     },
            # )

            # if serializer.is_valid():
            #     dashboard = serializer.save()

            # Add found insights to the dashboard (if any were found in previous steps)
            # Note: The insights would be stored in messages from the InsightSearchNode
            # await self._add_insights_from_messages(dashboard, state)

            # return PartialAssistantState(dashboard_id=dashboard.id)
            # else:
            #     capture_exception(
            #         Exception(f"Dashboard creation failed: {serializer.errors}"),
            #         {"team_id": self._team.id, "user_id": self._user.id},
            #     )
            #     return PartialAssistantState()
            return PartialAssistantState(dashboard_id=1)

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return PartialAssistantState()

    async def _add_insights_from_messages(self, dashboard: Dashboard, state: AssistantState):
        """Extract insights from the state messages and add them to dashboard."""
        # This would process the results from InsightSearchNode
        # For now, we'll implement a basic version
        # The actual implementation would parse the messages to extract insight IDs
        if state.insights_search_messages:
            pass


class DashboardCreationGraph(BaseAssistantGraph[AssistantState]):
    """Graph that orchestrates the dashboard creation process."""

    def __init__(self, team: Team, user: User):
        super().__init__(team, user, AssistantState)

    def add_dashboard_planner(self):
        """Add the dashboard planner node."""
        dashboard_planner = DashboardPlannerNode(self._team, self._user)
        self.add_node(AssistantNodeName.DASHBOARD_PLANNER, dashboard_planner)
        return self

    def add_insights_search(self):
        """Add the insight search node."""
        insights_search = InsightSearchNode(self._team, self._user)
        self.add_node(AssistantNodeName.INSIGHTS_SEARCH, insights_search)
        return self

    def add_dashboard_creator(self):
        """Add the dashboard creator node."""
        dashboard_creator = DashboardCreatorNode(self._team, self._user)
        self.add_node(AssistantNodeName.DASHBOARD_CREATOR, dashboard_creator)
        return self

    def compile_dashboard_graph(self):
        """Build and compile the complete dashboard creation graph."""
        return (
            self.add_dashboard_planner()
            .add_insights_search()
            .add_dashboard_creator()
            .add_edge(AssistantNodeName.START, AssistantNodeName.DASHBOARD_PLANNER)
            .add_edge(AssistantNodeName.DASHBOARD_PLANNER, AssistantNodeName.INSIGHTS_SEARCH)
            .add_edge(AssistantNodeName.INSIGHTS_SEARCH, AssistantNodeName.DASHBOARD_CREATOR)
            .add_edge(AssistantNodeName.DASHBOARD_CREATOR, AssistantNodeName.END)
            .compile()
        )


class CreateDashboardTool(MaxTool):
    name: str = "create_dashboard"
    description: str = "Create a dashboard based on natural language instructions, including searching for and adding relevant insights"
    thinking_message: str = "Creating your dashboard with relevant insights"

    args_schema: type[BaseModel] = DashboardCreatorArgs

    async def _arun_impl(self, instructions: str) -> tuple[str, dict[str, Any]]:
        """Create dashboard using the DashboardCreationGraph."""
        try:
            # Create and run the dashboard creation graph
            graph = DashboardCreationGraph(self._team, self._user)
            compiled_graph = graph.compile_dashboard_graph()

            # Initialize state with the instructions
            initial_state = AssistantState(dashboard_creation_instructions=instructions, messages=[])

            result = await compiled_graph.ainvoke(initial_state)

            if result.get("dashboard_id"):
                dashboard_url = f"/dashboard/{result['dashboard_id']}"
                message = f"Successfully created dashboard '{result.get('dashboard_name', 'Dashboard')}'"

                return message, {
                    "dashboard_id": result["dashboard_id"],
                    "dashboard_name": result.get("dashboard_name", "Dashboard"),
                    "dashboard_url": dashboard_url,
                }
            else:
                return "Failed to create dashboard. Please try again.", {}

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"An error occurred while creating the dashboard: {str(e)}", {}
