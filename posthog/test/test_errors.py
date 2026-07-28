from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.errors import QueryErrorCategory, classify_query_error


class TestClassifyQueryError(SimpleTestCase):
    @parameterized.expand(
        [
            # A funnel step referencing a deleted action raises a DRF ValidationError during query
            # building. It's invalid user input, so it must classify as USER_ERROR (→ SLO SUCCESS,
            # not captured to error tracking), not fall through to ERROR (→ FAILURE, captured).
            ("drf_validation_error", DRFValidationError("Action ID 12 does not exist!"), QueryErrorCategory.USER_ERROR),
            ("unclassified_exception", RuntimeError("boom"), QueryErrorCategory.ERROR),
        ]
    )
    def test_classify_query_error(self, _name, error, expected):
        assert classify_query_error(error) == expected
