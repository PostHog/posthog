"""Shared SQL fragment builders used by both the row-level and partitioned read paths.

The projection logic lives in `common/sql/projection`. This module's
`build_select_clause` wraps `compute_projected_columns` and renders each
identifier through `psycopg.sql.Identifier` so psycopg's escaping rules
apply — keeps the Postgres callers handing a `sql.Composable` to
`sql.SQL(...).format(...)`.
"""

from __future__ import annotations

from typing import Optional

from psycopg import sql

from posthog.temporal.data_imports.sources.common.sql.projection import compute_projected_columns


def build_select_clause(
    enabled_columns: Optional[list[str]],
    primary_keys: Optional[list[str]],
    incremental_field: Optional[str],
) -> sql.Composable:
    """Build the SELECT-list fragment for a Postgres read.

    Returns `sql.SQL("*")` when no projection applies, otherwise a
    comma-joined `sql.Identifier(...)` sequence — same SQL the previous
    in-module implementation produced. PKs + active incremental field
    are always retained; see `common/sql/projection.compute_projected_columns`.
    """
    projected = compute_projected_columns(enabled_columns, primary_keys, incremental_field)
    if projected is None:
        return sql.SQL("*")
    return sql.SQL(", ").join(sql.Identifier(column) for column in projected)
