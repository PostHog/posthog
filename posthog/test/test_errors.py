from django.test import SimpleTestCase

from clickhouse_driver.errors import ServerException

from posthog.errors import ExposedCHQueryError, QueryErrorCategory, classify_query_error, wrap_clickhouse_query_error


class TestScalarSubqueryError(SimpleTestCase):
    """A multi-row scalar subquery (CH code 125) is user-driven (e.g. a HogQL breakdown expression),
    so it must surface as a user-facing 400, not an unhandled 500."""

    def _make_error(self) -> ServerException:
        return ServerException(
            "DB::Exception: Scalar subquery returned more than one row. Stack trace: ...",
            code=125,
        )

    def test_scalar_subquery_error_is_exposed(self) -> None:
        wrapped = wrap_clickhouse_query_error(self._make_error())
        assert isinstance(wrapped, ExposedCHQueryError)
        assert getattr(wrapped, "code_name", None) == "incorrect_result_of_scalar_subquery"

    def test_scalar_subquery_error_has_actionable_message(self) -> None:
        message = str(wrap_clickhouse_query_error(self._make_error()))
        assert "DB::Exception" not in message
        assert "Stack trace" not in message
        assert "more than one row" in message

    def test_scalar_subquery_error_classified_as_user_error(self) -> None:
        # USER_ERROR keeps it out of error reporting rather than being captured as a 500.
        assert classify_query_error(self._make_error()) == QueryErrorCategory.USER_ERROR
