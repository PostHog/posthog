from django.test import SimpleTestCase

from clickhouse_driver.errors import ServerException

from posthog.errors import ExposedCHQueryError, QueryErrorCategory, classify_query_error, wrap_clickhouse_query_error


class TestClickhouseErrorClassification(SimpleTestCase):
    def test_too_many_query_plan_optimizations_is_user_safe(self) -> None:
        err = ServerException("Too many optimizations applied to query plan. Current limit 10000", code=572)

        wrapped = wrap_clickhouse_query_error(err)

        # Must stay user-safe so it's returned as a 4xx with a helpful message and kept out of error
        # tracking, rather than being captured as an internal ClickHouse error.
        assert isinstance(wrapped, ExposedCHQueryError)
        assert classify_query_error(wrapped) == QueryErrorCategory.USER_ERROR
        assert "too complex" in str(wrapped)
