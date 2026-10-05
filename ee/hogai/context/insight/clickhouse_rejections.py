"""Explain a ClickHouse rejection whose raw message stays internal.

Some ClickHouse errors embed stored data values in their text, so the query layer keeps that text
internal. Without it, the caller only learns that the query failed and rewrites it by trial and
error. The error name is safe to show, and for the common rejections it is enough to name the fix.
"""

from posthog.errors import USER_ERROR_CODE_NAMES

_CORRECTIONS: dict[str, str] = {
    "unknown_identifier": (
        "A column or alias in the query does not exist where ClickHouse reads it. Look up the table "
        "columns in `system.information_schema.columns`. In a join, prefix each column with its "
        "table alias."
    ),
}


def describe_clickhouse_rejection(code_name: str | None) -> str | None:
    """Name a ClickHouse rejection of the query and its fix, or None if the query did not cause it."""
    if not code_name or code_name not in USER_ERROR_CODE_NAMES:
        return None
    message = (
        f"ClickHouse rejected the query with error {code_name.upper()}. "
        "The full ClickHouse message is not shown because it can contain stored data values."
    )
    correction = _CORRECTIONS.get(code_name)
    return f"{message} {correction}" if correction else message
