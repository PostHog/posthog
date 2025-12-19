from typing import TYPE_CHECKING

import posthoganalytics

from posthog.schema import AgentMode

from ee.hogai.tools import CreateAndQueryInsightTool, CreateDashboardTool, CreateInsightTool, SessionSummarizationTool
from ee.hogai.utils.feature_flags import has_agent_modes_feature_flag

from ..factory import AgentModeDefinition
from ..toolkit import AgentToolkit

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


class ProductAnalyticsAgentToolkit(AgentToolkit):
    @property
    def tools(self) -> list[type["MaxTool"]]:
        tools: list[type[MaxTool]] = []

        if has_agent_modes_feature_flag(self._team, self._user):
            tools.append(CreateInsightTool)
        else:
            # The contextual insights tool overrides the static tool. Only inject if it's injected.
            if not CreateAndQueryInsightTool.is_editing_mode(self._context_manager):
                tools.append(CreateAndQueryInsightTool)
            if self._has_session_summarization_feature_flag():
                tools.append(SessionSummarizationTool)

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
