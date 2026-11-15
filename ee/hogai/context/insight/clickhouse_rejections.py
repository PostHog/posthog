"""Explain a ClickHouse rejection whose raw message stays internal.

Some ClickHouse errors embed stored data values in their text, so the query layer keeps that text
internal. Without it, the caller only learns that the query failed and rewrites it by trial and
error. The error name is safe to show, and for the common rejections it is enough to name the fix.
"""

from posthog.errors import internal_ch_error_user_message, is_clickhouse_query_rejection

_CORRECTIONS: dict[str, str] = {
    "UNKNOWN_IDENTIFIER": (
        "Look up the table columns in `system.information_schema.columns`. In a join, prefix each column with its "
        "table alias."
    ),
}


def describe_clickhouse_rejection(code_name: str | None, message: str | None = None) -> str | None:
    """Name a ClickHouse rejection of the query and its fix, or None if the query did not cause it."""
    if not code_name or not is_clickhouse_query_rejection(code_name):
        return None
    message = message or internal_ch_error_user_message(code_name)
    correction = _CORRECTIONS.get(code_name.upper())
    return f"{message} {correction}" if correction else message
