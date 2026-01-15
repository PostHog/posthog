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
                "Code: 439. DB::Exception: Cannot schedule a task: cannot allocate thread (threads=36, jobs=36). (CANNOT_SCHEDULE_TASK) (version 25.8.12.129 (official build))",
                code=439,
            ),
            "ClickHouseAtCapacity",
            "Queries are a little too busy right now. We're working to free up resources. Please try again later.",
            None,
            "CHQueryErrorCannotScheduleTask",
        ),
        (
            ServerException(
                "Code: 159. DB::Exception: Timeout exceeded: elapsed 60.046752587 seconds, maximum: 60. (TIMEOUT_EXCEEDED) (version 25.8.12.129 (official build))",
                code=159,
            ),
            "ClickHouseQueryTimeOut",
            "Query has hit the max execution time before completing. See our docs for how to improve your query performance. You may need to materialize.",
            None,
            "CHQueryErrorTimeoutExceeded",
        ),
        (
            ServerException(
                "Code: 499. DB::Exception: Failed to get object info: No response body.. HTTP response code: 404: while reading file.parquet",
                code=499,
            ),
            "CHQueryErrorS3Error",
            "Code: 499.\nS3 error occurred. Try again later.",
            499,
            "CHQueryErrorS3Error",
        ),
        (
            ServerException(
                "Code: 43. DB::Exception: Illegal type String of argument of function toInt64.",
                code=43,
            ),
            "CHQueryErrorIllegalTypeOfArgument",
            "Illegal type String of argument of function toInt64.",
            43,
            "CHQueryErrorIllegalTypeOfArgument",
        ),
        (
            ServerException(
                "Code: 386. DB::Exception: There is no common type for types String, Int64.",
                code=386,
            ),
            "CHQueryErrorNoCommonType",
            "There is no common type for types String, Int64.",
            386,
            "CHQueryErrorNoCommonType",
        ),
        (
            ServerException(
                "Code: 215. DB::Exception: Column count is not an aggregate function.",
                code=215,
            ),
            "CHQueryErrorNotAnAggregate",
            "Column count is not an aggregate function.",
            215,
            "CHQueryErrorNotAnAggregate",
        ),
        (
            ServerException(
                "Code: 46. DB::Exception: Unknown function foobar.",
                code=46,
            ),
            "CHQueryErrorUnknownFunction",
            "Unknown function foobar.",
            46,
            "CHQueryErrorUnknownFunction",
        ),
        (
            ServerException(
                "Code: 53. DB::Exception: Type mismatch in IN or VALUES section.",
                code=53,
            ),
            "CHQueryErrorTypeMismatch",
            "Type mismatch in IN or VALUES section.",
            53,
            "CHQueryErrorTypeMismatch",
        ),
        (
            ServerException(
                "Code: 184. DB::Exception: Aggregate function sum(count()) is found inside another aggregate function.",
                code=184,
            ),
            "CHQueryErrorIllegalAggregation",
            "Aggregate function sum(count()) is found inside another aggregate function.",
            184,
            "CHQueryErrorIllegalAggregation",
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
