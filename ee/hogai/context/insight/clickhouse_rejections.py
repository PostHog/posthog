"""Explain a ClickHouse rejection whose raw message stays internal.

Some ClickHouse errors embed stored data values in their text, so the query layer keeps that text
internal. Without it, the caller only learns that the query failed and rewrites it by trial and
error. The error name is safe to show, and for the common rejections it is enough to name the fix.
"""

from posthog.errors import CLICKHOUSE_ERROR_CODE_LOOKUP, QueryErrorCategory

_NUMERIC_PARSE_CORRECTION = (
    "A value does not parse as the target type. This often happens when a property holds an empty "
    "string. `CAST(x AS Int)` and `CAST(x AS Float)` fail on such a value. Use `toInt(x)` or "
    "`toFloat(x)` instead, because they return NULL for a value that does not parse. Wrap the call "
    "in `ifNull(..., 0)` if the query needs a number in every row."
)

_CORRECTIONS: dict[str, str] = {
    "cannot_parse_text": _NUMERIC_PARSE_CORRECTION,
    "cannot_parse_number": _NUMERIC_PARSE_CORRECTION,
    "invalid_join_on_expression": (
        "ClickHouse cannot run this JOIN ON condition. Use only equality conditions between the two "
        "tables, such as `a.id = b.id`, combined with AND. Move OR conditions, inequalities, and "
        "filters on one table into WHERE, or filter that table in a subquery before the join."
    ),
    "unknown_identifier": (
        "A column or alias in the query does not exist where ClickHouse reads it. Look up the table "
        "columns in `system.information_schema.columns`. In a join, prefix each column with its "
        "table alias."
    ),
}

_USER_ERROR_CODE_NAMES = frozenset(
    meta.name.lower()
    for meta in CLICKHOUSE_ERROR_CODE_LOOKUP.values()
    if meta.get_category() == QueryErrorCategory.USER_ERROR
)


def describe_clickhouse_rejection(code_name: str | None) -> str | None:
    """Name a ClickHouse rejection of the query and its fix, or None if the query did not cause it."""
    if not code_name or code_name not in _USER_ERROR_CODE_NAMES:
        return None
    message = (
        f"ClickHouse rejected the query with error {code_name.upper()}. "
        "The full ClickHouse message is not shown because it can contain stored data values."
    )
    correction = _CORRECTIONS.get(code_name)
    return f"{message} {correction}" if correction else message
