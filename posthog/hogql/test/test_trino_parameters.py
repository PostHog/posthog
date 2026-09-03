import pytest

from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.trino_parameters import convert_pyformat_placeholders


def test_convert_pyformat_placeholders_preserves_occurrence_order() -> None:
    sql, values = convert_pyformat_placeholders(
        "SELECT %(second)s, %(first)s, %(second)s",
        {"first": "a", "second": "b"},
    )

    assert sql == "SELECT ?, ?, ?"
    assert values == ["b", "a", "b"]


def test_convert_pyformat_placeholders_rejects_missing_values() -> None:
    with pytest.raises(ExposedHogQLError, match="Missing bound value"):
        convert_pyformat_placeholders("SELECT %(missing)s", {})


def test_convert_pyformat_placeholders_ignores_quoted_placeholder_shapes() -> None:
    sql, values = convert_pyformat_placeholders(
        "SELECT '%(literal)s', \"%(identifier)s\", %(bound)s, 'it''s %(still_literal)s'",
        {"bound": "value"},
    )

    assert sql == "SELECT '%(literal)s', \"%(identifier)s\", ?, 'it''s %(still_literal)s'"
    assert values == ["value"]
