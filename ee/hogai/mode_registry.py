from posthog.schema import AgentMode

from ee.hogai.graph.agent_modes.presets.product_analytics import product_analytics_agent

MODE_REGISTRY = {
    AgentMode.PRODUCT_ANALYTICS: product_analytics_agent,
}
