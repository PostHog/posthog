"""Column-projection helpers shared by every SQL source.

Semantics:
- `enabled_columns is None` → `SELECT *`.
- `enabled_columns == []` → primary keys + incremental field only.
- PKs + active incremental field are always retained: merges break without PKs,
  incremental can't advance without its cursor field.
- Order: caller's list first, then missing PKs, then incremental field.
- Empty result falls back to `None` so callers emit `SELECT *` instead of `SELECT  FROM`.
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
    """Return ordered column names to project, or `None` for `SELECT *`."""
    if enabled_columns is None:
        return None

    seen: set[str] = set()
    ordered: list[str] = []
    for column in enabled_columns:
        if column not in seen:
            seen.add(column)
            ordered.append(column)
    for column in primary_keys or []:
        if column not in seen:
            seen.add(column)
            ordered.append(column)
    if incremental_field and incremental_field not in seen:
        ordered.append(incremental_field)

    if not ordered:
        return None

    return ordered


def format_projected_select_clause(
    projected_columns: list[str] | None,
    quoter: IdentifierQuoter,
) -> str:
    """Render projection as a SELECT-clause fragment. `None` → `"*"`."""
    if projected_columns is None:
        return "*"
    return ", ".join(quoter.quote(column) for column in projected_columns)


def filter_columns_by_enabled_columns(
    columns: list[tuple[str, str, bool]],
    enabled_columns: list[str] | None,
    primary_keys: list[str] | None,
    incremental_field: str | None = None,
) -> list[tuple[str, str, bool]]:
    """Filter `(name, type, nullable)` tuples to the projection."""
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
    """Filter `DataWarehouseTable.columns`-shaped dict to the projection."""
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
    """Project a `Table` to retained columns in source order.

    Empty intersection returns the input unchanged so the Arrow schema stays in
    lockstep with `cursor.description` instead of going empty.
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
    """Drop `enabled_columns` entries missing from the source. Returns `(kept, removed)`."""
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
