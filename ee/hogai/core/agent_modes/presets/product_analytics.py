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
1. Search for existing dashboards that might be related to revenue
2. Search for existing insights that might be related to revenue metrics
3. Retrieve the taxonomy and understand the schema
4. Retrieve the data warehouse schema to find the relevant tables
5. Present to the user a plan of insights to create for the revenue dashboard
6. Create new insights for the revenue metrics if none are found
7. Create a new dashboard with the insights
8. Analyze the created dashboard and provide a concise summary of metrics
*Begins working on the first task*
""".strip()

DASHBOARD_CREATION_TODO_EXAMPLE_REASONING = """
The assistant used the todo list because:
1. The user requested to create a dashboard. This is a complex task that requires multiple steps to complete.
2. Multiple searches are necessary to find the relevant data (insights, dashboards, taxonomy, data warehouse schema, etc.).
3. The assistant needs to keep track of the insights to be added to the dashboard.
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
