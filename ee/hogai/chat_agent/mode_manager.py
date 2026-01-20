from posthog.schema import AgentMode

from posthog.models import Team, User

from ee.hogai.chat_agent.prompt_builder import ChatAgentPromptBuilder
from ee.hogai.chat_agent.toolkit import ChatAgentToolkit, ChatAgentToolkitManager
from ee.hogai.context import AssistantContextManager
from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.mode_manager import AgentModeManager
from ee.hogai.core.agent_modes.presets.error_tracking import error_tracking_agent
from ee.hogai.core.agent_modes.presets.product_analytics import product_analytics_agent
from ee.hogai.core.agent_modes.presets.session_replay import session_replay_agent
from ee.hogai.core.agent_modes.presets.sql import sql_agent
from ee.hogai.core.agent_modes.prompt_builder import AgentPromptBuilder
from ee.hogai.core.agent_modes.toolkit import AgentToolkit, AgentToolkitManager
from ee.hogai.utils.feature_flags import has_error_tracking_mode_feature_flag
from ee.hogai.utils.types.base import AssistantState, NodePath

# Default mode registry for normal chat agent operation
DEFAULT_CHAT_AGENT_MODE_REGISTRY: dict[AgentMode, AgentModeDefinition] = {
    AgentMode.PRODUCT_ANALYTICS: product_analytics_agent,
    AgentMode.SQL: sql_agent,
    AgentMode.SESSION_REPLAY: session_replay_agent,
}


class ChatAgentModeManager(AgentModeManager):
    def __init__(
        self,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...],
        context_manager: AssistantContextManager,
        state: AssistantState,
    ):
        super().__init__(
            team=team,
            user=user,
            node_path=node_path,
            context_manager=context_manager,
            state=state,
        )

    @property
    def mode_registry(self) -> dict[AgentMode, AgentModeDefinition]:
        registry = dict(DEFAULT_CHAT_AGENT_MODE_REGISTRY)
        if has_error_tracking_mode_feature_flag(self._team, self._user):
            registry[AgentMode.ERROR_TRACKING] = error_tracking_agent
        return registry

    @property
    def prompt_builder_class(self) -> type[AgentPromptBuilder]:
        return ChatAgentPromptBuilder

    @property
    def toolkit_class(self) -> type[AgentToolkit]:
        return ChatAgentToolkit

    @property
    def toolkit_manager_class(self) -> type[AgentToolkitManager]:
        return ChatAgentToolkitManager
