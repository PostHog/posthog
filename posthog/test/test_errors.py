from clickhouse_driver.errors import ServerException

from posthog.errors import ExposedCHQueryError, wrap_clickhouse_query_error


def test_unknown_type_is_wrapped_as_user_error():
    # Invalid data types in user/AI-authored queries (e.g. Nullable(Object)) are user
    # errors, not internal failures, so they must not land in error tracking.
    err = ServerException("Unknown data type family: Object", code=50)

    wrapped = wrap_clickhouse_query_error(err)

    assert isinstance(wrapped, ExposedCHQueryError)
    assert wrapped.code == 50


def test_logical_error_stays_internal():
    err = ServerException("boom", code=49)

    wrapped = wrap_clickhouse_query_error(err)

    assert not isinstance(wrapped, ExposedCHQueryError)
    assert wrapped.code == 49
