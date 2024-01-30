import unittest
from ee.clickhouse.queries.experiments.funnel_experiment_result import (
    validate_event_variants as validate_funnel_event_variants,
)
from ee.clickhouse.queries.experiments.trend_experiment_result import (
    validate_event_variants as validate_trend_event_variants,
)
from rest_framework.exceptions import ValidationError


class TestFunnelExperiments(unittest.TestCase):
    def test_validate_event_variants_no_events(self):
        expected_code = "no-events"
        with self.assertRaises(ValidationError) as context:
            validate_funnel_event_variants([], ["test", "control"])

        self.assertEqual(expected_code, context.exception.detail[0].code)

    def test_validate_event_variants_missing_variants(self):
        funnel_results = [
            [
                {
                    "action_id": "step-a-1",
                    "name": "step-a-1",
                    "custom_name": None,
                    "order": 0,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                    "breakdown": ["test"],
                    "breakdown_value": ["test"],
                },
                {
                    "action_id": "step-a-2",
                    "name": "step-a-2",
                    "custom_name": None,
                    "order": 1,
                    "people": [],
                    "count": 0,
                    "type": "events",
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                    "breakdown": ["test"],
                    "breakdown_value": ["test"],
                },
            ]
        ]

        expected_code = "missing-flag-variants::control"
        with self.assertRaises(ValidationError) as context:
            validate_funnel_event_variants(funnel_results, ["test", "control"])

        self.assertEqual(expected_code, context.exception.detail[0].code)

    def test_validate_event_variants_ignore_old_variant(self):
        funnel_results = [
            [
                {
                    "action_id": "step-a-1",
                    "name": "step-a-1",
                    "custom_name": None,
                    "order": 0,
                    "people": [],
                    "count": 1,
                    "type": "events",
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                    "breakdown": ["test"],
                    "breakdown_value": ["test"],
                },
                {
                    "action_id": "step-a-2",
                    "name": "step-a-2",
                    "custom_name": None,
                    "order": 1,
                    "people": [],
                    "count": 0,
                    "type": "events",
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                    "breakdown": ["old-variant"],
                    "breakdown_value": ["old-variant"],
                },
            ]
        ]

        expected_code = "missing-flag-variants::control"
        with self.assertRaises(ValidationError) as context:
            validate_funnel_event_variants(funnel_results, ["test", "control"])

        self.assertEqual(expected_code, context.exception.detail[0].code)


class TestTrendExperiments(unittest.TestCase):
    def test_validate_event_variants_no_events(self):
        expected_code = "no-events"
        with self.assertRaises(ValidationError) as context:
            validate_trend_event_variants([], ["test", "control"])

        self.assertEqual(expected_code, context.exception.detail[0].code)

    def test_validate_event_variants_missing_variants(self):
        insight_results = [
            {
                "action": {
                    "id": "step-b-0",
                    "type": "events",
                    "order": 0,
                    "name": "step-b-0",
                },
                "label": "test",
                "breakdown_value": "test",
            }
        ]

        expected_code = "missing-flag-variants::control"
        with self.assertRaises(ValidationError) as context:
            validate_trend_event_variants(insight_results, ["test", "control"])

        self.assertEqual(expected_code, context.exception.detail[0].code)
