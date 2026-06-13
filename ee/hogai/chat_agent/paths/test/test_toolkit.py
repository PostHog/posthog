from posthog.test.base import BaseTest

from ee.hogai.chat_agent.paths.toolkit import generate_paths_schema


class TestPathsToolkit(BaseTest):
    def test_generate_paths_schema_sorts_top_level_properties(self):
        schema = generate_paths_schema()
        properties = schema["parameters"]["properties"]["query"]["properties"]
        property_keys = list(properties.keys())

        expected_order = [
            "kind",
            "pathsFilter",
            "dateRange",
            "properties",
        ]

        for i, expected_key in enumerate(expected_order):
            self.assertEqual(
                property_keys[i],
                expected_key,
                f"Expected {expected_key} at position {i}, got {property_keys[i]}",
            )
