from clickhouse_driver.errors import ServerException

from posthog.errors import ExposedCHQueryError, QueryErrorCategory, classify_query_error, wrap_clickhouse_query_error


class TestWrapClickhouseQueryError:
    def test_too_large_distributed_depth_is_user_safe(self):
        # Code 581 is raised for over-complex queries that nest distributed subqueries too deeply.
        # It must surface as a user-facing error, not an internal exception sent to error reporting.
        err = ServerException("DB::Exception: Maximum distributed depth exceeded", code=581)

        wrapped = wrap_clickhouse_query_error(err)

        assert isinstance(wrapped, ExposedCHQueryError)
        assert "too complex" in str(wrapped)
        assert classify_query_error(wrapped) == QueryErrorCategory.USER_ERROR
