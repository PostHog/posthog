from typing import TYPE_CHECKING

import posthoganalytics

from posthog.schema import AgentMode

from ee.hogai.tools import CreateDashboardTool, CreateInsightTool, UpsertDashboardTool
from ee.hogai.tools.todo_write import POSITIVE_TODO_EXAMPLES, TodoWriteExample
from ee.hogai.utils.feature_flags import has_upsert_dashboard_feature_flag

from ..factory import AgentModeDefinition
from ..toolkit import AgentToolkit

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


DASHBOARD_CREATION_TODO_EXAMPLE_EXAMPLE = """
User: Generate a revenue dashboard
Assistant: I'll help you create a revenue dashboard. Let me make a todo list to track this implementation.
1. List (the list_data tool with kind="dashboards") the existing dashboards
2. List saved insights using the list_data tool with kind="insights"
3. Validate promising insights by reading their schemas (the read_data tool with insight_id)
4. Retrieve the taxonomy and understand the schema (the read_taxonomy tool)
5. Retrieve the data warehouse schema to find the relevant tables (the read_data tool)
6. Create new insights for missing metrics only if no existing insight matches
7. Create a new dashboard with the insights
8. Analyze the created dashboard and provide a concise summary of metrics
*Begins working on the first task*
""".strip()

DASHBOARD_CREATION_TODO_EXAMPLE_REASONING = """
The assistant used the todo list because:
1. The user requested to create a dashboard. This is a complex task that requires multiple steps to complete.
2. Finding existing insights requires both listing (to discover insights with different naming using the list_data tool) and searching (by keywords using the search tool).
3. Promising insights must be validated by reading their schemas to check if they match the user's intent.
4. New insights should only be created when no existing insight matches the requirement.
""".strip()


class ProductAnalyticsAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        *POSITIVE_TODO_EXAMPLES,
        TodoWriteExample(
            example=DASHBOARD_CREATION_TODO_EXAMPLE_EXAMPLE,
            reasoning=DASHBOARD_CREATION_TODO_EXAMPLE_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        tools: list[type[MaxTool]] = [CreateInsightTool]

        # Add other lower-priority tools
        if has_upsert_dashboard_feature_flag(self._team, self._user):
            tools.append(UpsertDashboardTool)
        else:
            tools.append(CreateDashboardTool)

        return tools

    def _has_session_summarization_feature_flag(self) -> bool:
        """
        Check if the user has the session summarization feature flag enabled.
        """
        return posthoganalytics.feature_enabled(
            "max-session-summarization",
            str(self._user.distinct_id),
            groups={"organization": str(self._team.organization_id)},
            group_properties={"organization": {"id": str(self._team.organization_id)}},
            send_feature_flag_events=False,
        )


product_analytics_agent = AgentModeDefinition(
    mode=AgentMode.PRODUCT_ANALYTICS,
    mode_description="General-purpose mode for product analytics tasks.",
    toolkit_class=ProductAnalyticsAgentToolkit,
)
