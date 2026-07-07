from posthog.test.base import BaseTest

from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode

from ee.hogai.context import AssistantContextManager
from ee.hogai.core.agent_modes.presets.customer_analytics import (
    CUSTOMER_ANALYTICS_MODE_DESCRIPTION,
    POSITIVE_EXAMPLE_ACCOUNT_USAGE_SPIKE,
    CustomerAnalyticsAgentToolkit,
    customer_analytics_agent,
)

# Raw mechanics of the account→group bridge that must never surface in user-facing
# prompt text — the mode is a façade. Tool descriptions may state external_id's meaning,
# but the mode description and trajectory examples must not expose the plumbing.
_LEAKY_TERMS = ["group_key", "$group_", "aggregation_group_type_index", "group_type_index"]


class TestCustomerAnalyticsPreset(BaseTest):
    def test_mode_definition_wires_toolkit(self):
        self.assertEqual(customer_analytics_agent.mode, AgentMode.CUSTOMER_ANALYTICS)
        self.assertEqual(customer_analytics_agent.toolkit_class, CustomerAnalyticsAgentToolkit)

    def test_toolkit_exposes_account_tools(self):
        context_manager = AssistantContextManager(
            team=self.team, user=self.user, config=RunnableConfig(configurable={})
        )
        toolkit = CustomerAnalyticsAgentToolkit(team=self.team, user=self.user, context_manager=context_manager)
        tool_names = [tool.model_fields["name"].default for tool in toolkit.tools]

        self.assertIn("upsert_account", tool_names)
        self.assertIn("upsert_account_notebook", tool_names)

    def test_prompt_does_not_leak_bridge_mechanics(self):
        examples = "\n".join(
            f"{example.example}\n{example.reasoning}"
            for example in CustomerAnalyticsAgentToolkit.POSITIVE_TODO_EXAMPLES
        )
        surface_text = f"{CUSTOMER_ANALYTICS_MODE_DESCRIPTION}\n{examples}".lower()

        for term in _LEAKY_TERMS:
            self.assertNotIn(term.lower(), surface_text)

    def test_usage_spike_example_is_wired_into_todo_examples(self):
        # A defined-but-unused trajectory example is dead code — it never reaches the agent.
        wired_examples = [example.example for example in CustomerAnalyticsAgentToolkit.POSITIVE_TODO_EXAMPLES]

        self.assertIn(POSITIVE_EXAMPLE_ACCOUNT_USAGE_SPIKE, wired_examples)
