from unittest import TestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.api.query import _extract_validation_code


class TestQueryValidationMetrics(TestCase):
    @parameterized.expand(
        [
            (
                "string_code",
                ValidationError("bad request", code="stickiness_criteria_negative"),
                "stickiness_criteria_negative",
            ),
            (
                "list_code",
                ValidationError(["bad request"], code="stickiness_interval_count_non_positive"),
                "stickiness_interval_count_non_positive",
            ),
            (
                "dict_code",
                ValidationError({"intervalCount": ["bad request"]}, code="stickiness_interval_count_too_large"),
                "stickiness_interval_count_too_large",
            ),
        ]
    )
    def test_extracts_validation_code(self, _name: str, error: ValidationError, expected_code: str) -> None:
        self.assertEqual(_extract_validation_code(error), expected_code)
