from posthog.test.base import BaseTest

from ee.hogai.chat_agent.retention.toolkit import generate_retention_schema


class TestRetentionToolkit(BaseTest):
    def test_generate_retention_schema_sorts_top_level_properties(self):
        schema = generate_retention_schema()
        properties = schema["parameters"]["properties"]["query"]["properties"]
        property_keys = list(properties.keys())

        expected_order = [
            "kind",
            "retentionFilter",
            "dateRange",
            "properties",
        ]

        for i, expected_key in enumerate(expected_order):
            assert property_keys[i] == expected_key, f"Expected {expected_key} at position {i}, got {property_keys[i]}"
