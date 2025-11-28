from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ee.hogai.tools.replay.filter_session_recordings import FilterSessionRecordingsTool
from ee.hogai.tools.replay.summarize_sessions import SummarizeSessionsTool

from ..factory import AgentModeDefinition
from ..toolkit import AgentToolkit

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


class SessionReplayAgentToolkit(AgentToolkit):
    @property
    def tools(self) -> list[type["MaxTool"]]:
        tools: list[type[MaxTool]] = [FilterSessionRecordingsTool, SummarizeSessionsTool]
        return tools


session_replay_agent = AgentModeDefinition(
    mode=AgentMode.SESSION_REPLAY,
    mode_description="Specialized mode for analyzing session recordings and user behavior. This mode allows you to filter session recordings, and summarize entire sessions or a set of them.",
    toolkit_class=SessionReplayAgentToolkit,
)
