from django.test import SimpleTestCase

from clickhouse_driver.errors import ServerException
from parameterized import parameterized

from posthog.errors import (
    CHQueryErrorResourceLimitExceeded,
    ExposedCHQueryError,
    InternalCHQueryError,
    wrap_clickhouse_query_error,
)


class TestWrapClickhouseQueryError(SimpleTestCase):
    @parameterized.expand(
        [
            ("too_many_rows", 158, "Limit for rows exceeded"),
            ("too_many_columns", 161, "Limit for columns exceeded"),
            ("query_is_too_large", 229, "Query is too large"),
            ("limit_exceeded", 290, "Limit exceeded"),
        ]
    )
    def test_resource_limit_errors_are_exposed_with_actionable_hint(self, _name, code, message):
        wrapped = wrap_clickhouse_query_error(ServerException(message, code=code))
        assert isinstance(wrapped, CHQueryErrorResourceLimitExceeded)
        assert isinstance(wrapped, ExposedCHQueryError)
        assert "Try reducing its scope by changing the time range." in str(wrapped)

    def test_generic_error_without_performance_category_stays_internal(self):
        # A code with no dedicated branch and no QUERY_PERFORMANCE_ERROR category (e.g. an
        # internal ClickHouse invariant failure) must not be exposed to the user.
        wrapped = wrap_clickhouse_query_error(ServerException("Logical error: something impossible happened", code=49))
        assert isinstance(wrapped, InternalCHQueryError)
        assert not isinstance(wrapped, ExposedCHQueryError)
