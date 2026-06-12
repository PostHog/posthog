"""psycopg rendering of row-filter predicates for Postgres / Redshift.

Kept separate from `predicates.py` so the psycopg import stays off the serializer
import path (the serializer only needs the driver-free validation in `predicates`).

Values are emitted as `sql.Literal` — psycopg adapts them server-side, so they are
never string-interpolated. Column names use `sql.Identifier` (psycopg quotes and
escapes them). The operator is the already-normalized canonical operator from
`ValidatedRowFilter`, so wrapping it in `sql.SQL` is safe.
"""

from __future__ import annotations

from psycopg import sql

from posthog.temporal.data_imports.sources.common.sql.predicates import ValidatedRowFilter


def render_psycopg_row_filter_conditions(filters: list[ValidatedRowFilter]) -> list[sql.Composable]:
    """Render each row filter as a `<col> <op> <literal>` psycopg composable."""
    return [
        sql.SQL("{col} {op} {val}").format(
            col=sql.Identifier(row_filter.column),
            op=sql.SQL(row_filter.operator),
            val=sql.Literal(row_filter.value),
        )
        for row_filter in filters
    ]


def and_join(conditions: list[sql.Composable]) -> sql.Composable:
    """AND-join a list of composable conditions into one composable."""
    return sql.SQL(" AND ").join(conditions)
