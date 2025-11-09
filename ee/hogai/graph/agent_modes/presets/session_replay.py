from typing import TYPE_CHECKING

import posthoganalytics

from posthog.schema import AgentMode

from ee.hogai.tools.replay.summarize_sessions import SummarizeSessionsTool

from ..factory import AgentDefinition
from ..nodes import AgentToolkit

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


class SessionReplayAgentToolkit(AgentToolkit):
    @property
    def custom_tools(self) -> list[type["MaxTool"]]:
        tools: list[type[MaxTool]] = []

        # Add session summarization tool if enabled
        if self._has_session_summarization_feature_flag():
            tools.append(SummarizeSessionsTool)

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


session_replay_agent = AgentDefinition(
    mode=AgentMode.SESSION_REPLAY,
    mode_description="Specialized mode for analyzing session recordings and user behavior. This mode allows you to get summaries of session recordings and insights about them in natural language.",
    toolkit_class=SessionReplayAgentToolkit,
)
