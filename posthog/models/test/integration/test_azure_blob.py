import pytest

from posthog.models.integration.azure_blob import strip_leading_whitespace


@pytest.mark.parametrize(
    "conn_str,expected",
    [
        # No changes without leading whitespace
        ("AccountName=name;AccountKey=key;SomeKey=value", "AccountName=name;AccountKey=key;SomeKey=value"),
        # Stripped leading whitespace one time
        ("AccountName=name; AccountKey=key;SomeKey=value", "AccountName=name;AccountKey=key;SomeKey=value"),
        # Stripped leading whitespace two times
        ("AccountName=name; AccountKey=key; SomeKey=value", "AccountName=name;AccountKey=key;SomeKey=value"),
    ],
)
def test_strip_leading_whitespace(conn_str: str, expected: str) -> None:
    assert strip_leading_whitespace(conn_str) == expected
