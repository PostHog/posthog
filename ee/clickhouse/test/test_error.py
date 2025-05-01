import pytest
from clickhouse_driver.errors import ServerException

from posthog.errors import wrap_query_error, ch_error_type


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
            "CHQueryErrorMemoryLimitExceeded",
            "Query exceeds memory limits. Try reducing its scope by changing the time range.",
            241,
            "CHQueryErrorMemoryLimitExceeded",
        ),
        (
            ServerException("Too many simultaneous queries. Maximum: 100.", code=202),
            "ClickhouseAtCapacity",
            "Clickhouse cluster is at capacity. Please try this query again later.",
            None,
            "CHQueryErrorTooManySimultaneousQueries",
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
