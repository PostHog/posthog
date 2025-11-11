from typing import TYPE_CHECKING

import posthoganalytics

from posthog.schema import AgentMode

from ee.hogai.tools import CreateAndQueryInsightTool, CreateDashboardTool, CreateInsightTool

from ..factory import AgentModeDefinition
from ..nodes import AgentToolkit
from ..utils import has_agent_modes_feature_flag

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


class ProductAnalyticsAgentToolkit(AgentToolkit):
    @property
    def custom_tools(self) -> list[type["MaxTool"]]:
        tools: list[type[MaxTool]] = []

        if has_agent_modes_feature_flag(self._team, self._user):
            tools.append(CreateInsightTool)
        else:
            # The contextual insights tool overrides the static tool. Only inject if it's injected.
            if not CreateAndQueryInsightTool.is_editing_mode(self._context_manager):
                tools.append(CreateAndQueryInsightTool)

        # Add other lower-priority tools
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
