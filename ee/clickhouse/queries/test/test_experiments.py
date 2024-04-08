import json
import unittest
from ee.clickhouse.queries.experiments.funnel_experiment_result import (
    validate_event_variants as validate_funnel_event_variants,
)
from ee.clickhouse.queries.experiments.trend_experiment_result import (
    validate_event_variants as validate_trend_event_variants,
)
from rest_framework.exceptions import ValidationError

from posthog.constants import ExperimentNoResultsErrorKeys


class TestFunnelExperiments(unittest.TestCase):
    def test_validate_event_variants_no_events(self):
        funnel_results = []

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EVENTS: True,
                ExperimentNoResultsErrorKeys.NO_FLAG_INFO: True,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
            }
        )

        with self.assertRaises(ValidationError) as context:
            validate_funnel_event_variants(funnel_results, ["test", "control"])

        self.assertEqual(context.exception.detail[0], expected_errors)

    def test_validate_event_variants_no_control(self):
        funnel_results = [
            [
                {
                    "action_id": "funnel-step-1",
                    "name": "funnel-step-1",
                    "order": 0,
                    "breakdown": ["test"],
                    "breakdown_value": ["test"],
                },
                {
                    "action_id": "funnel-step-2",
                    "name": "funnel-step-2",
                    "order": 1,
                    "breakdown": ["test"],
                    "breakdown_value": ["test"],
                },
            ]
        ]

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EVENTS: False,
                ExperimentNoResultsErrorKeys.NO_FLAG_INFO: False,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: False,
            }
        )

        with self.assertRaises(ValidationError) as context:
            validate_funnel_event_variants(funnel_results, ["test", "control"])

        self.assertEqual(context.exception.detail[0], expected_errors)

    def test_validate_event_variants_no_test(self):
        funnel_results = [
            [
                {
                    "action_id": "funnel-step-1",
                    "name": "funnel-step-1",
                    "order": 0,
                    "breakdown": ["control"],
                    "breakdown_value": ["control"],
                },
                {
                    "action_id": "funnel-step-2",
                    "name": "funnel-step-2",
                    "order": 1,
                    "breakdown": ["control"],
                    "breakdown_value": ["control"],
                },
            ]
        ]

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EVENTS: False,
                ExperimentNoResultsErrorKeys.NO_FLAG_INFO: False,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: False,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
            }
        )

        with self.assertRaises(ValidationError) as context:
            validate_funnel_event_variants(funnel_results, ["test", "control"])

        self.assertEqual(context.exception.detail[0], expected_errors)

    def test_validate_event_variants_no_flag_info(self):
        funnel_results = [
            [
                {
                    "action_id": "funnel-step-1",
                    "name": "funnel-step-1",
                    "order": 0,
                    "breakdown": [""],
                    "breakdown_value": [""],
                },
                {
                    "action_id": "funnel-step-2",
                    "name": "funnel-step-2",
                    "order": 1,
                    "breakdown": [""],
                    "breakdown_value": [""],
                },
            ]
        ]

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EVENTS: False,
                ExperimentNoResultsErrorKeys.NO_FLAG_INFO: True,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
            }
        )

        with self.assertRaises(ValidationError) as context:
            validate_funnel_event_variants(funnel_results, ["test", "control"])

        self.assertEqual(context.exception.detail[0], expected_errors)


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

    def test_validate_event_variants_missing_control(self):
        insight_results = [
            {
                "action": {
                    "id": "step-b-0",
                    "type": "events",
                    "order": 0,
                    "name": "step-b-0",
                },
                "label": "test_1",
                "breakdown_value": "test_1",
            }
        ]

        # Only 1 test variant is required to return results
        expected_code = "missing-flag-variants::control"
        with self.assertRaises(ValidationError) as context:
            validate_trend_event_variants(insight_results, ["control", "test_1", "test_2"])

        self.assertEqual(expected_code, context.exception.detail[0].code)

    def test_validate_event_variants_ignore_old_variant(self):
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
            },
            {
                "action": {
                    "id": "step-b-0",
                    "type": "events",
                    "order": 0,
                    "name": "step-b-0",
                },
                "label": "test",
                "breakdown_value": "old-variant",
            },
        ]

        expected_code = "missing-flag-variants::control"
        with self.assertRaises(ValidationError) as context:
            validate_trend_event_variants(insight_results, ["test", "control"])

        self.assertEqual(expected_code, context.exception.detail[0].code)
