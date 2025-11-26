from posthog.test.base import BaseTest

from ee.hogai.chat_agent.trends.toolkit import generate_trends_schema


class TestTrendsToolkit(BaseTest):
    def test_generate_trends_schema_sorts_top_level_properties(self):
        schema = generate_trends_schema()
        properties = schema["parameters"]["properties"]["query"]["properties"]
        property_keys = list(properties.keys())

        expected_order = [
            "kind",
            "series",
            "dateRange",
            "interval",
            "trendsFilter",
            "properties",
            "breakdownFilter",
        ]

        for i, expected_key in enumerate(expected_order):
            self.assertEqual(
                property_keys[i],
                expected_key,
                f"Expected {expected_key} at position {i}, got {property_keys[i]}",
            )
