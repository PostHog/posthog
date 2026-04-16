from unittest import TestCase

from rest_framework.exceptions import ValidationError

from posthog.api.query import _extract_validation_code


class TestQueryValidationMetrics(TestCase):
    def test_extracts_string_code(self):
        error = ValidationError("bad request", code="stickiness_criteria_negative")

        self.assertEqual(_extract_validation_code(error), "stickiness_criteria_negative")

    def test_extracts_list_code(self):
        error = ValidationError(["bad request"], code="stickiness_interval_count_non_positive")

        self.assertEqual(_extract_validation_code(error), "stickiness_interval_count_non_positive")

    def test_extracts_dict_code(self):
        error = ValidationError({"intervalCount": ["bad request"]}, code="stickiness_interval_count_too_large")

        self.assertEqual(_extract_validation_code(error), "stickiness_interval_count_too_large")
