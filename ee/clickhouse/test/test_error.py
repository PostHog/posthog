import pytest

from clickhouse_driver.errors import ServerException

from posthog.errors import ch_error_type, wrap_query_error


@pytest.mark.parametrize(
    "error,expected_type,expected_message,expected_code,expected_ch_error",
    [
        (AttributeError("Foobar"), "AttributeError", "Foobar", None, "AttributeError"),
        (
            ServerException("Estimated query execution time (34.5 seconds) is too long. Aborting query", code=160),
            "EstimatedQueryExecutionTimeTooLong",
            "Estimated query execution time (34.5 seconds) is too long. Try reducing its scope by changing the time range.",
            None,
            "CHQueryErrorTooSlow",
        ),
        (
            ServerException("Syntax error", code=62),
            "CHQueryErrorSyntaxError",
            "Code: 62.\nSyntax error",
            62,
            "CHQueryErrorSyntaxError",
        ),
        (
            ServerException("Syntax error", code=9999),
            "CHQueryErrorUnknownException",
            "Code: 9999.\nSyntax error",
            9999,
            "CHQueryErrorUnknownException",
        ),
        (
            ServerException(
                "Memory limit (for query) exceeded: would use 42.00 GiB (attempt to allocate chunk of 16757643 bytes), maximum: 42.00 GiB.",
                code=241,
            ),
            "ClickHouseQueryMemoryLimitExceeded",
            "Query has reached the max memory limit before completing. See our docs for how to improve your query memory footprint. You may need to narrow date range or materialize.",
            None,
            "CHQueryErrorMemoryLimitExceeded",
        ),
        (
            ServerException("Too many simultaneous queries. Maximum: 100.", code=202),
            "ClickHouseAtCapacity",
            "Queries are a little too busy right now. We're working to free up resources. Please try again later.",
            None,
            "CHQueryErrorTooManySimultaneousQueries",
        ),
        (
            ServerException(
                "Code: 439. DB::Exception: Cannot schedule a task: cannot allocate thread (threads=36, jobs=36). (CANNOT_SCHEDULE_TASK) (version 24.8.14.39 (official build))",
                code=439,
            ),
            "ClickHouseAtCapacity",
            "Queries are a little too busy right now. We're working to free up resources. Please try again later.",
            None,
            "CHQueryErrorCannotScheduleTask",
        ),
        (
            ServerException(
                "Code: 159. DB::Exception: Timeout exceeded: elapsed 60.046752587 seconds, maximum: 60. (TIMEOUT_EXCEEDED) (version 24.8.7.41 (official build))",
                code=159,
            ),
            "ClickHouseQueryTimeOut",
            "Query has hit the max execution time before completing. See our docs for how to improve your query performance. You may need to materialize.",
            None,
            "CHQueryErrorTimeoutExceeded",
        ),
    ],
)
def test_wrap_query_error(error, expected_type, expected_message, expected_code, expected_ch_error):
    label = ch_error_type(error)
    new_error = wrap_query_error(error)
    assert type(new_error).__name__ == expected_type
    assert str(new_error) == expected_message
    assert getattr(new_error, "code", None) == expected_code
    assert label == expected_ch_error
