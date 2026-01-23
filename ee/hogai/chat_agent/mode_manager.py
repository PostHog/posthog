from typing import cast

from posthog.schema import AgentMode

from posthog.models import Team, User

from ee.hogai.chat_agent.prompt_builder import ChatAgentPlanPromptBuilder, ChatAgentPromptBuilder
from ee.hogai.chat_agent.toolkit import (
    ChatAgentPlanToolkit,
    ChatAgentToolkit,
    ChatAgentToolkitManager,
    PlanModeSwitchAgentToolkit,
)
from ee.hogai.context import AssistantContextManager
from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.mode_manager import AgentModeManager
from ee.hogai.core.agent_modes.presets.error_tracking import chat_agent_plan_error_tracking_agent, error_tracking_agent
from ee.hogai.core.agent_modes.presets.product_analytics import (
    chat_agent_plan_product_analytics_agent,
    product_analytics_agent,
)
from ee.hogai.core.agent_modes.presets.session_replay import chat_agent_plan_session_replay_agent, session_replay_agent
from ee.hogai.core.agent_modes.presets.sql import chat_agent_plan_sql_agent, sql_agent
from ee.hogai.core.agent_modes.prompt_builder import AgentPromptBuilder
from ee.hogai.core.agent_modes.toolkit import AgentToolkit, AgentToolkitManager
from ee.hogai.utils.feature_flags import has_error_tracking_mode_feature_flag, has_plan_mode_feature_flag
from ee.hogai.utils.types.base import AssistantState, NodePath

# Execution and plan mode definitions - fictitious modes used to trigger transition in and out of plan mode
execution_agent = AgentModeDefinition(
    mode=AgentMode.EXECUTION,
    mode_description="Switch to this mode when the user has approved your plan to proceed with execution.",
    toolkit_class=PlanModeSwitchAgentToolkit,
)

plan_agent = AgentModeDefinition(
    mode=AgentMode.PLAN,
    mode_description="Switch to this mode when you need to plan a complex task that requires multiple steps and approvals.",
    toolkit_class=PlanModeSwitchAgentToolkit,
)

# Default mode registry for normal chat agent operation
DEFAULT_CHAT_AGENT_MODE_REGISTRY: dict[AgentMode, AgentModeDefinition] = {
    AgentMode.PRODUCT_ANALYTICS: product_analytics_agent,
    AgentMode.SQL: sql_agent,
    AgentMode.SESSION_REPLAY: session_replay_agent,
}

DEFAULT_CHAT_AGENT_PLAN_MODE_REGISTRY: dict[AgentMode, AgentModeDefinition] = {
    AgentMode.PRODUCT_ANALYTICS: chat_agent_plan_product_analytics_agent,
    AgentMode.SQL: chat_agent_plan_sql_agent,
    AgentMode.SESSION_REPLAY: chat_agent_plan_session_replay_agent,
    AgentMode.EXECUTION: execution_agent,
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

        # Handle plan mode: agent_mode=PLAN from frontend means supermode=PLAN
        self._supermode: AgentMode | None
        if state.agent_mode == AgentMode.PLAN:
            self._supermode = AgentMode.PLAN
            self._mode = AgentMode.PRODUCT_ANALYTICS
        else:
            self._supermode = cast(AgentMode | None, state.supermode)
            self._mode = state.agent_mode or AgentMode.PRODUCT_ANALYTICS

    @property
    def mode_registry(self) -> dict[AgentMode, AgentModeDefinition]:
        if self._supermode == AgentMode.PLAN:
            registry = dict(DEFAULT_CHAT_AGENT_PLAN_MODE_REGISTRY)
        else:
            registry = dict(DEFAULT_CHAT_AGENT_MODE_REGISTRY)
            if has_plan_mode_feature_flag(self._team, self._user):
                registry[AgentMode.PLAN] = plan_agent
        if has_error_tracking_mode_feature_flag(self._team, self._user):
            if self._supermode == AgentMode.PLAN:
                registry[AgentMode.ERROR_TRACKING] = chat_agent_plan_error_tracking_agent
            else:
                registry[AgentMode.ERROR_TRACKING] = error_tracking_agent
        return registry

    @property
    def prompt_builder_class(self) -> type[AgentPromptBuilder]:
        if self._supermode == AgentMode.PLAN:
            return ChatAgentPlanPromptBuilder
        return ChatAgentPromptBuilder

    @property
    def toolkit_class(self) -> type[AgentToolkit]:
        if self._supermode == AgentMode.PLAN:
            return ChatAgentPlanToolkit
        return ChatAgentToolkit

    @property
    def toolkit_manager_class(self) -> type[AgentToolkitManager]:
        return ChatAgentToolkitManager
