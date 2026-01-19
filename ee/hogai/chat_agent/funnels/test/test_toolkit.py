from posthog.test.base import BaseTest

from ee.hogai.chat_agent.funnels.toolkit import generate_funnel_schema


class TestFunnelToolkit(BaseTest):
    def test_generate_funnel_schema_sorts_top_level_properties(self):
        schema = generate_funnel_schema()
        properties = schema["parameters"]["properties"]["query"]["properties"]
        property_keys = list(properties.keys())

        expected_order = [
            "kind",
            "series",
            "dateRange",
            "interval",
            "funnelsFilter",
            "properties",
            "breakdownFilter",
        ]

        for i, expected_key in enumerate(expected_order):
            self.assertEqual(
                property_keys[i],
                expected_key,
                f"Expected {expected_key} at position {i}, got {property_keys[i]}",
            )
