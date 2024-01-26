import unittest
from ee.clickhouse.queries.experiments.funnel_experiment_result import validate_event_variants
from rest_framework.exceptions import ValidationError


class TestExperiments(unittest.TestCase):
    def test_validate_event_variants(self):
        expected_message = "No experiment events have been ingested yet"
        with self.assertRaises(ValidationError) as context:
            validate_event_variants([], ["test", "control"])

        self.assertIn(expected_message, str(context.exception))

    def test_validate_event_variants_2(self):
        filtered_results = [
            [
                {
                    "action_id": "step-2",
                    "name": "step-2",
                    "custom_name": None,
                    "order": 1,
                    "people": [],
                    "count": 3,
                    "type": "events",
                    "average_conversion_time": 0.3333333333333333,
                    "median_conversion_time": 0.0,
                    "breakdown": ["control"],
                    "breakdown_value": ["control"],
                }
            ]
        ]

        expected_message = "No events for the first funnel step have been ingested yet"
        with self.assertRaises(ValidationError) as context:
            validate_event_variants(filtered_results, ["test", "control"])

        self.assertIn(expected_message, str(context.exception))

    def test_validate_event_variants_3(self):
        filtered_results = [
            [
                {
                    "action_id": "step-1",
                    "name": "step-1",
                    "custom_name": None,
                    "order": 0,
                    "people": [],
                    "count": 3,
                    "type": "events",
                    "average_conversion_time": 0.3333333333333333,
                    "median_conversion_time": 0.0,
                    "breakdown": ["control"],
                    "breakdown_value": ["control"],
                }
            ]
        ]

        expected_message = "No experiment events have been ingested yet for the following variants: test"
        with self.assertRaises(ValidationError) as context:
            validate_event_variants(filtered_results, ["test", "control"])

        self.assertIn(expected_message, str(context.exception))
