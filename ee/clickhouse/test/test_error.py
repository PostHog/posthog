import pytest
from clickhouse_driver.errors import ServerException

from posthog.errors import wrap_query_error


@pytest.mark.parametrize(
    "error,expected_type,expected_message,expected_code",
    [
        (AttributeError("Foobar"), "AttributeError", "Foobar", None),
        (
            ServerException("Estimated query execution time (34.5 seconds) is too long. Aborting query"),
            "EstimatedQueryExecutionTimeTooLong",
            "Estimated query execution time (34.5 seconds) is too long.",
            None,
        ),
        (ServerException("Syntax error", code=62), "CHQueryErrorSyntaxError", "Code: 62.\nSyntax error", 62),
        (ServerException("Syntax error", code=9999), "CHQueryErrorUnknownException", "Code: 9999.\nSyntax error", 9999),
    ],
)
def test_wrap_query_error(error, expected_type, expected_message, expected_code):
    new_error = wrap_query_error(error)
    assert type(new_error).__name__ == expected_type
    assert str(new_error) == expected_message
    assert getattr(new_error, "code", None) == expected_code
