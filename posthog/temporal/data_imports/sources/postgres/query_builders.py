"""Shared SQL fragment builders for the row-level and partitioned read paths.

Projection logic lives in `common/sql/projection`. Here we wrap it with
`psycopg.sql.Identifier` so callers can compose `sql.Composable` fragments.
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
    """Build the SELECT-list fragment as a `psycopg.sql.Composable`."""
    projected = compute_projected_columns(enabled_columns, primary_keys, incremental_field)
    if projected is None:
        return sql.SQL("*")
    return sql.SQL(", ").join(sql.Identifier(column) for column in projected)
