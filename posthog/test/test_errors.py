from django.test import SimpleTestCase

from clickhouse_driver.errors import ServerException

from posthog.errors import (
    CHQueryErrorNumberOfArgumentsDoesntMatch,
    ExposedCHQueryError,
    QueryErrorCategory,
    look_up_clickhouse_error_code_meta,
    wrap_clickhouse_query_error,
)


class TestWrapClickhouseQueryError(SimpleTestCase):
    def test_number_of_arguments_doesnt_match_is_user_safe(self):
        # A wrong-arity function call is the user's query mistake, not a backend bug — it must
        # surface as an exposed (user-safe) error so it isn't captured into error tracking.
        server_error = ServerException(
            "DB::Exception: Number of arguments for function plus doesn't match: "
            "passed 3, should be 2. Stack trace: ...",
            code=42,
        )
        wrapped = wrap_clickhouse_query_error(server_error)

        assert isinstance(wrapped, CHQueryErrorNumberOfArgumentsDoesntMatch)
        assert isinstance(wrapped, ExposedCHQueryError)
        assert look_up_clickhouse_error_code_meta(server_error).get_category() == QueryErrorCategory.USER_ERROR
