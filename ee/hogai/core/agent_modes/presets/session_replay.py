from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ee.hogai.tools.replay.summarize_sessions import SummarizeSessionsTool

from ..factory import AgentModeDefinition
from ..toolkit import AgentToolkit

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


class SessionReplayAgentToolkit(AgentToolkit):
    @property
    def tools(self) -> list[type["MaxTool"]]:
        tools: list[type[MaxTool]] = [SummarizeSessionsTool]
        return tools


session_replay_agent = AgentModeDefinition(
    mode=AgentMode.SESSION_REPLAY,
    mode_description="Specialized mode for analyzing session recordings and user behavior. This mode allows you to get summaries of session recordings and insights about them in natural language.",
    toolkit_class=SessionReplayAgentToolkit,
)
