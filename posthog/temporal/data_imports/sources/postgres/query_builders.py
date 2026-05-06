"""Shared SQL fragment builders used by both the row-level and partitioned read paths."""

from __future__ import annotations

from typing import Optional

from psycopg import sql


def build_select_clause(
    enabled_columns: Optional[list[str]],
    primary_keys: Optional[list[str]],
    incremental_field: Optional[str],
) -> sql.Composable:
    # `None` and `[]` are distinct: `None` means sync all (`SELECT *`), `[]` means PKs + incremental only.
    if enabled_columns is None:
        return sql.SQL("*")

    retained: set[str] = set(enabled_columns)
    for pk in primary_keys or []:
        retained.add(pk)
    if incremental_field:
        retained.add(incremental_field)

    seen: set[str] = set()
    ordered: list[str] = []
    for column in enabled_columns:
        if column in retained and column not in seen:
            seen.add(column)
            ordered.append(column)
    for column in primary_keys or []:
        if column in retained and column not in seen:
            seen.add(column)
            ordered.append(column)
    if incremental_field and incremental_field in retained and incremental_field not in seen:
        ordered.append(incremental_field)

    return sql.SQL(", ").join(sql.Identifier(column) for column in ordered)
