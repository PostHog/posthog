from posthog.schema import AgentMode

from ee.hogai.graph.agent.presets.product_analytics import product_analytics_agent
from ee.hogai.graph.agent.presets.sql import sql_agent

MODE_REGISTRY = {
    AgentMode.PRODUCT_ANALYTICS: product_analytics_agent,
    AgentMode.SQL: sql_agent,
}
