from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.errors import (
    QueryError,
    ResolutionError,
    SyntaxError as HogQLSyntaxError,
)

from posthog.errors import CHQueryErrorIllegalTypeOfArgument
from posthog.exceptions_capture import capture_exception

from products.data_modeling.backend.models.modeling import BoundedResolverError


class TestCaptureExceptionSkipsUserQueryErrors(SimpleTestCase):
    @parameterized.expand(
        [
            ("resolve_field", QueryError("Unable to resolve field: gross_price")),
            ("bad_syntax", HogQLSyntaxError("mismatched input")),
            # A QueryError subclass defined outside posthog.hogql.errors still classifies as USER_ERROR.
            ("bounded_resolver", BoundedResolverError("Unable to resolve field: s")),
            ("user_safe_clickhouse", CHQueryErrorIllegalTypeOfArgument("illegal type of argument", code=43)),
        ]
    )
    def test_user_input_query_errors_are_not_sent_to_error_tracking(self, _name, error):
        with (
            patch("posthoganalytics.api_key", "x"),
            patch("posthoganalytics.capture_exception") as mock_capture,
        ):
            assert capture_exception(error) is None
            mock_capture.assert_not_called()

    @parameterized.expand(
        [
            # Internal resolver errors and query performance limits can signal real platform problems,
            # so they must stay captured — only the USER_ERROR bucket is skipped.
            ("internal_hogql_error", ResolutionError("resolver bug")),
            ("generic_error", ValueError("boom")),
        ]
    )
    def test_platform_defects_are_still_captured(self, _name, error):
        with (
            patch("posthoganalytics.api_key", "x"),
            patch("posthoganalytics.capture_exception", return_value="event-id") as mock_capture,
        ):
            capture_exception(error)
            mock_capture.assert_called_once()
