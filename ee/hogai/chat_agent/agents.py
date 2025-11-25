from pydantic import BaseModel

from posthog.schema import AgentMode

from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.presets.product_analytics import product_analytics_agent
from ee.hogai.core.agent_modes.presets.session_replay import session_replay_agent
from ee.hogai.core.agent_modes.presets.sql import sql_agent
from ee.hogai.utils.types.base import AgentType

DEFAULT_MODE_REGISTRY: dict[AgentMode, AgentModeDefinition] = {
    AgentMode.PRODUCT_ANALYTICS: product_analytics_agent,
    AgentMode.SQL: sql_agent,
    AgentMode.SESSION_REPLAY: session_replay_agent,
}


class AgentDescription(BaseModel):
    description: str
    default_mode: AgentMode
    mode_registry: dict[AgentMode, AgentModeDefinition]


CHAT_AGENTS: dict[AgentType, AgentDescription] = {
    AgentType.GENERAL_PURPOSE: AgentDescription(
        description="General purpose agent that can handle a wide range of product analytics tasks.",
        default_mode=AgentMode.PRODUCT_ANALYTICS,
        mode_registry=DEFAULT_MODE_REGISTRY,
    ),
    AgentType.SQL: AgentDescription(
        description="Agent that can handle SQL queries.",
        default_mode=AgentMode.SQL,
        mode_registry=DEFAULT_MODE_REGISTRY,
    ),
    AgentType.SESSION_REPLAY: AgentDescription(
        description="Agent that can handle session replay tasks.",
        default_mode=AgentMode.SESSION_REPLAY,
        mode_registry=DEFAULT_MODE_REGISTRY,
    ),
}
