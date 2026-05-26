"""Column-projection helpers shared by every SQL source.

Centralizes the "enabled_columns + primary_keys + incremental_field"
projection rules that used to live in Postgres-specific helpers. Pure
logic — no driver-specific quoting — so each SQL source can plug it
into its own query builder.

Semantics:

- `enabled_columns is None` means "sync every column" (`SELECT *`).
- `enabled_columns == []` means "sync only the always-retained
  columns" (primary keys + incremental field).
- Primary keys and the active incremental field are **always retained**
  regardless of `enabled_columns` — merges break without PKs, and the
  pipeline can't advance the incremental cursor without its field.
- Order preserved: caller's `enabled_columns` first, then any
  primary-key columns not already listed, then the incremental field if
  it wasn't already listed.
- Fallback: when projection would emit nothing (e.g. `enabled_columns=[]`
  on a table with no PKs and no incremental field), the helpers return
  `None` so the caller can fall back to `SELECT *` rather than emit an
  empty column list.
"""

from __future__ import annotations

from typing import TypeVar

from posthog.temporal.data_imports.sources.common.sql.identifiers import IdentifierQuoter
from posthog.temporal.data_imports.sources.common.sql.types import Column, Table

_TColumnValue = TypeVar("_TColumnValue")
_ColumnT = TypeVar("_ColumnT", bound=Column)


def compute_projected_columns(
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None = None,
    incremental_field: str | None = None,
) -> list[str] | None:
    """Resolve the ordered list of column names to project.

    Returns `None` when the caller should emit `SELECT *` — either
    because `enabled_columns is None` (sync everything) or because the
    projection would be empty (no PKs / incremental field to retain).

    The returned order is deterministic: `enabled_columns` first (in
    the order the caller supplied), then PK columns the caller did not
    already include, then the incremental field if missing.
    """
    if enabled_columns is None:
        return None

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

    if not ordered:
        # `enabled_columns=[]` on a table with no PKs / incremental field would otherwise emit
        # `SELECT  FROM …`. Fall back to `*` rather than blow up the sync with a syntax error.
        return None

    return ordered


def format_projected_select_clause(
    projected_columns: list[str] | None,
    quoter: IdentifierQuoter,
) -> str:
    """Format a projected column list as a SQL fragment for `SELECT <clause> FROM ...`.

    `None` (no projection) renders as `"*"`. Identifiers go through
    `quoter`, which runs the shared allowlist check before quoting.
    Use this for drivers that emit SQL as plain strings (MySQL, MSSQL,
    Snowflake, BigQuery, Redshift). Postgres callers prefer
    `compute_projected_columns` and wrap each name in
    `psycopg.sql.Identifier` so psycopg's escaping rules apply.
    """
    if projected_columns is None:
        return "*"
    return ", ".join(quoter.quote(column) for column in projected_columns)


def filter_columns_by_enabled_columns(
    columns: list[tuple[str, str, bool]],
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None,
    incremental_field: str | None = None,
) -> list[tuple[str, str, bool]]:
    """Filter raw `(name, type, nullable)` column tuples to the projection.

    `enabled_columns is None` returns the input unchanged. Used to project
    the column list we persist on `schema_metadata` / `DataWarehouseTable`
    so HogQL and Delta see the same shape as the source-side SELECT.
    """
    if enabled_columns is None:
        return columns
    retained: set[str] = set(enabled_columns)
    for pk in primary_keys or []:
        retained.add(pk)
    if incremental_field:
        retained.add(incremental_field)
    return [col for col in columns if col[0] in retained]


def filter_dwh_columns_by_enabled_columns(
    columns: dict[str, _TColumnValue],
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None,
    incremental_field: str | None = None,
) -> dict[str, _TColumnValue]:
    """Same as `filter_columns_by_enabled_columns` but for `DataWarehouseTable.columns` dicts.

    Generic over the value type so it works for both the
    Postgres-DWH-shaped dicts (`{name: {hogql, clickhouse, ...}}`) and any
    other shape future drivers may carry.
    """
    if enabled_columns is None:
        return columns
    retained: set[str] = set(enabled_columns)
    for pk in primary_keys or []:
        retained.add(pk)
    if incremental_field:
        retained.add(incremental_field)
    return {name: column for name, column in columns.items() if name in retained}


def project_arrow_columns(
    table: Table[_ColumnT],
    retained: list[str] | None,
) -> Table[_ColumnT]:
    """Return a new `Table` containing only the retained columns, in source order.

    `retained is None` returns the input unchanged. The Arrow schema we
    build off the resulting `Table` must match the projected SELECT or
    downstream consumers (Delta writer) will see column shape drift on a
    sync that runs after a projection change.
    """
    if retained is None:
        return table
    retained_set = set(retained)
    projected = [column for column in table.columns if column.name in retained_set]
    if not projected:
        return table
    return Table(name=table.name, columns=projected, parents=table.parents, alias=table.alias, type=table.type)


def prune_enabled_columns(
    enabled_columns: list[str] | None,
    available_column_names: set[str],
) -> tuple[list[str] | None, list[str]]:
    """Drop entries in `enabled_columns` that no longer exist at the source.

    Called from `reconcile_schema_metadata` so a source-side column drop
    doesn't break the next sync (which would emit `SELECT … missing_col`
    and fail). Returns `(pruned_enabled_columns, removed_names)`. The
    `removed_names` list is logged so we can monitor frequency.

    `enabled_columns is None` (sync-all) is left as-is — there's nothing
    stale to prune.
    """
    if enabled_columns is None:
        return None, []
    kept: list[str] = []
    removed: list[str] = []
    for column in enabled_columns:
        if column in available_column_names:
            kept.append(column)
        else:
            removed.append(column)
    return kept, removed
