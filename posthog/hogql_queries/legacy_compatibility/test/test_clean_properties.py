from posthog.test.base import BaseTest

from posthog.hogql_queries.legacy_compatibility.clean_properties import clean_entity_properties, clean_global_properties


class TestCleanGlobalProperties(BaseTest):
    def test_handles_empty_properties(self):
        properties: dict = {}

        result = clean_global_properties(properties)

        self.assertEqual(result, None)

    def test_handles_old_style_properties(self):
        properties = {"utm_medium__icontains": "email"}

        result = clean_global_properties(properties)

        self.assertEqual(
            result,
            {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "utm_medium", "operator": "icontains", "type": "event", "value": "email"}],
                    }
                ],
            },
        )

    def test_handles_property_filter_lists(self):
        properties = [{"key": "id", "type": "cohort", "value": 636, "operator": None}]

        result = clean_global_properties(properties)

        self.assertEqual(
            result,
            {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "id", "type": "cohort", "operator": "in", "value": 636}],
                    }
                ],
            },
        )

    def test_handles_property_group_filters(self):
        properties = {
            "type": "AND",
            "values": [{"type": "AND", "values": [{"key": "id", "type": "cohort", "value": 850, "operator": None}]}],
        }

        result = clean_global_properties(properties)

        self.assertEqual(
            result,
            {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "id", "type": "cohort", "operator": "in", "value": 850}],
                    }
                ],
            },
        )

    def test_handles_cohort_negation(self):
        properties = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [{"key": "id", "type": "cohort", "value": 850, "operator": None, "negation": True}],
                }
            ],
        }

        result = clean_global_properties(properties)

        self.assertEqual(
            result,
            {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "id", "type": "cohort", "operator": "not_in", "value": 850}],
                    }
                ],
            },
        )

    def test_handles_property_group_filters_values(self):
        properties = {
            "type": "AND",
            "values": [{"key": "id", "type": "cohort", "value": 850, "operator": None}],
        }

        result = clean_global_properties(properties)

        self.assertEqual(
            result,
            {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "id", "type": "cohort", "operator": "in", "value": 850}],
                    }
                ],
            },
        )


class TestCleanEntityProperties(BaseTest):
    def test_handles_empty_properties(self):
        properties: dict = {}

        result = clean_entity_properties(properties)

        self.assertEqual(result, None)

    def test_handles_old_style_properties(self):
        properties = {"utm_medium__icontains": "email"}

        result = clean_entity_properties(properties)

        self.assertEqual(
            result,
            [{"key": "utm_medium", "operator": "icontains", "type": "event", "value": "email"}],
        )

    def test_handles_property_filter_lists(self):
        properties = [
            {"key": "$current_url", type: "event", "value": "https://hedgebox.net/signup/", "operator": "exact"},
        ]

        result = clean_entity_properties(properties)

        self.assertEqual(
            result,
            [
                {"key": "$current_url", type: "event", "value": "https://hedgebox.net/signup/", "operator": "exact"},
            ],
        )

    def test_handles_property_group_values(self):
        properties = {
            "type": "AND",
            "values": [
                {
                    "key": "$current_url",
                    "operator": "exact",
                    "type": "event",
                    "value": "https://hedgebox.net/signup/",
                },
            ],
        }

        result = clean_entity_properties(properties)

        self.assertEqual(
            result,
            [
                {
                    "key": "$current_url",
                    "operator": "exact",
                    "type": "event",
                    "value": "https://hedgebox.net/signup/",
                },
            ],
        )
