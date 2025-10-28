from posthog.schema import AgentMode

from ee.hogai.graph.agent.factory import AgentDefinition

product_analytics_agent = AgentDefinition(AgentMode.PRODUCT_ANALYTICS, "Product Analytics Agent")

MODE_REGISTRY = {
    AgentMode.PRODUCT_ANALYTICS: product_analytics_agent,
}
