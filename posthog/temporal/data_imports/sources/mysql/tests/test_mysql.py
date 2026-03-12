import pytest

from posthog.temporal.data_imports.sources.mysql.mysql import _sanitize_identifier


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("mydb", "`mydb`"),
        ("851", "`851`"),
        ("$col", "`$col`"),
        ("db@prod", "`db@prod`"),
    ],
)
def test_sanitize_identifier_valid(identifier, expected):
    assert _sanitize_identifier(identifier) == expected


@pytest.mark.parametrize(
    "identifier",
    [
        "bad;id",
        "$bad!",
    ],
)
def test_sanitize_identifier_invalid(identifier):
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        _sanitize_identifier(identifier)
