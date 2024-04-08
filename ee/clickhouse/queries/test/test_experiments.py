import unittest
from ee.clickhouse.queries.experiments.funnel_experiment_result import (
    validate_event_variants as validate_funnel_event_variants,
)
from ee.clickhouse.queries.experiments.trend_experiment_result import (
    validate_event_variants as validate_trend_event_variants,
)
from rest_framework.exceptions import ValidationError


class TestFunnelExperiments(unittest.TestCase):
    # def test_validate_event_variants_no_events(self):
    #     expected_code = "no-events"
    #     with self.assertRaises(ValidationError) as context:
    #         validate_funnel_event_variants([], ["test", "control"])

    #     self.assertEqual(expected_code, context.exception.detail[0].code)

    # def test_validate_event_variants_missing_variants(self):
    #     funnel_results = [
    #         [
    #             {
    #                 "action_id": "step-a-1",
    #                 "name": "step-a-1",
    #                 "custom_name": None,
    #                 "order": 0,
    #                 "people": [],
    #                 "count": 1,
    #                 "type": "events",
    #                 "average_conversion_time": None,
    #                 "median_conversion_time": None,
    #                 "breakdown": ["test"],
    #                 "breakdown_value": ["test"],
    #             },
    #             {
    #                 "action_id": "step-a-2",
    #                 "name": "step-a-2",
    #                 "custom_name": None,
    #                 "order": 1,
    #                 "people": [],
    #                 "count": 0,
    #                 "type": "events",
    #                 "average_conversion_time": None,
    #                 "median_conversion_time": None,
    #                 "breakdown": ["test"],
    #                 "breakdown_value": ["test"],
    #             },
    #         ]
    #     ]

    #     expected_code = "missing-flag-variants::control"
    #     with self.assertRaises(ValidationError) as context:
    #         validate_funnel_event_variants(funnel_results, ["test", "control"])

    #     self.assertEqual(expected_code, context.exception.detail[0].code)

    # def test_validate_event_variants_missing_control(self):
    #     funnel_results = [
    #         [
    #             {
    #                 "action_id": "step-a-1",
    #                 "name": "step-a-1",
    #                 "custom_name": None,
    #                 "order": 0,
    #                 "people": [],
    #                 "count": 1,
    #                 "type": "events",
    #                 "average_conversion_time": None,
    #                 "median_conversion_time": None,
    #                 "breakdown": ["test_1"],
    #                 "breakdown_value": ["test_1"],
    #             },
    #             {
    #                 "action_id": "step-a-2",
    #                 "name": "step-a-2",
    #                 "custom_name": None,
    #                 "order": 1,
    #                 "people": [],
    #                 "count": 0,
    #                 "type": "events",
    #                 "average_conversion_time": None,
    #                 "median_conversion_time": None,
    #                 "breakdown": ["test_1"],
    #                 "breakdown_value": ["test_1"],
    #             },
    #         ]
    #     ]

    #     # Only 1 test variant is required to return results
    #     expected_code = "missing-flag-variants::control"
    #     with self.assertRaises(ValidationError) as context:
    #         validate_funnel_event_variants(funnel_results, ["control", "test_1", "test_2"])

    #     self.assertEqual(expected_code, context.exception.detail[0].code)

    # def test_validate_event_variants_ignore_old_variant(self):
    #     funnel_results = [
    #         [
    #             {
    #                 "action_id": "step-a-1",
    #                 "name": "step-a-1",
    #                 "custom_name": None,
    #                 "order": 0,
    #                 "people": [],
    #                 "count": 1,
    #                 "type": "events",
    #                 "average_conversion_time": None,
    #                 "median_conversion_time": None,
    #                 "breakdown": ["test"],
    #                 "breakdown_value": ["test"],
    #             },
    #             {
    #                 "action_id": "step-a-2",
    #                 "name": "step-a-2",
    #                 "custom_name": None,
    #                 "order": 1,
    #                 "people": [],
    #                 "count": 0,
    #                 "type": "events",
    #                 "average_conversion_time": None,
    #                 "median_conversion_time": None,
    #                 "breakdown": ["old-variant"],
    #                 "breakdown_value": ["old-variant"],
    #             },
    #         ]
    #     ]

    #     expected_code = "missing-flag-variants::control"
    #     with self.assertRaises(ValidationError) as context:
    #         validate_funnel_event_variants(funnel_results, ["test", "control"])

    #     self.assertEqual(expected_code, context.exception.detail[0].code)

    def test_validate_event_variants_no_events(self):
        funnel_results = []

        expected_errors = {"no-events": True, "no-flag-info": True, "no-control-variant": True, "no-test-variant": True}

        with self.assertRaises(ValidationError) as context:
            validate_funnel_event_variants(funnel_results, ["test", "control"])

        # Convert ErrorDetail objects to booleans
        received_errors = {key: (value == "True") for key, value in context.exception.detail.items()}

        self.assertEqual(received_errors, expected_errors)

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

        expected_errors = {
            "no-events": False,
            "no-flag-info": False,
            "no-control-variant": True,
            "no-test-variant": False,
        }

        with self.assertRaises(ValidationError) as context:
            validate_funnel_event_variants(funnel_results, ["test", "control"])

        # Convert ErrorDetail objects to booleans
        received_errors = {key: (value == "True") for key, value in context.exception.detail.items()}

        self.assertEqual(received_errors, expected_errors)

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

        expected_errors = {
            "no-events": False,
            "no-flag-info": False,
            "no-control-variant": False,
            "no-test-variant": True,
        }

        with self.assertRaises(ValidationError) as context:
            validate_funnel_event_variants(funnel_results, ["test", "control"])

        # Convert ErrorDetail objects to booleans
        received_errors = {key: (value == "True") for key, value in context.exception.detail.items()}

        self.assertEqual(received_errors, expected_errors)

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

        expected_errors = {
            "no-events": False,
            "no-flag-info": True,
            "no-control-variant": True,
            "no-test-variant": True,
        }

        with self.assertRaises(ValidationError) as context:
            validate_funnel_event_variants(funnel_results, ["test", "control"])

        # Convert ErrorDetail objects to booleans
        received_errors = {key: (value == "True") for key, value in context.exception.detail.items()}

        self.assertEqual(received_errors, expected_errors)

    # def test_funnel_no_events(self):
    #     funnel_results = [
    #         [
    #             {
    #                 "action_id": "funnel-step-1",
    #                 "name": "funnel-step-1",
    #                 "custom_name": None,
    #                 "order": 0,
    #                 "people": [],
    #                 "count": 1,
    #                 "type": "events",
    #                 "average_conversion_time": None,
    #                 "median_conversion_time": None,
    #                 "breakdown": ["test"],
    #                 "breakdown_value": ["test"],
    #             },
    #             {
    #                 "action_id": "funnel-step-2",
    #                 "name": "funnel-step-2",
    #                 "custom_name": None,
    #                 "order": 1,
    #                 "people": [],
    #                 "count": 0,
    #                 "type": "events",
    #                 "average_conversion_time": None,
    #                 "median_conversion_time": None,
    #                 "breakdown": ["test"],
    #                 "breakdown_value": ["test"],
    #             },
    #         ]
    #     ]

    #     expected_code = "missing-flag-variants::control"
    #     with self.assertRaises(ValidationError) as context:
    #         validate_funnel_event_variants(funnel_results, ["test", "control"])

    #     self.assertEqual(expected_code, context.exception.detail[0].code)


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
