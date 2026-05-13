"""Enumeration activities — read source-of-truth metadata and return refs.

Each `enumerate_*` activity returns a list of small dataclasses (one per
table-like thing). The workflow chunks them and feeds them into the matching
`upsert_*_batch` activity. Splitting enumerate from upsert keeps the read
phase cheap and lets the workflow control batch sizing.

This commit ships the warehouse enumeration. Saved query / native / system
table enumerators land in subsequent commits.
"""

import asyncio
from dataclasses import dataclass

from temporalio import activity

from products.data_warehouse.backend.models.table import DataWarehouseTable


@dataclass
class WarehouseColumnRef:
    """Lightweight column descriptor — what the catalog needs to materialize a CatalogColumn."""

    name: str
    clickhouse_type: str | None
    nullable: bool


@dataclass
class WarehouseTableRef:
    """One imported warehouse table. The `id` ties back to DataWarehouseTable
    via the catalog node's GenericForeignKey."""

    id: str  # UUID string — Temporal serializes UUID as text anyway
    name: str
    columns: list[WarehouseColumnRef]


@activity.defn
async def enumerate_warehouse_tables(team_id: int) -> list[WarehouseTableRef]:
    """Return refs for every non-deleted warehouse table belonging to the team."""
    return await asyncio.to_thread(_enumerate_warehouse_tables_sync, team_id)


def _enumerate_warehouse_tables_sync(team_id: int) -> list[WarehouseTableRef]:
    # DataWarehouseTable.columns is a dict {col_name: type_info}. type_info can
    # be either a plain string (old style) or `{"clickhouse": "...", "valid": bool}`
    # (current style). Mirror the parsing in `DataWarehouseTable.hogql_definition`.
    refs: list[WarehouseTableRef] = []
    # Plain iteration — the default manager already select_related()s, so
    # .only() conflicts and iterator() needs an explicit chunk_size. Typical
    # teams have at most a few hundred warehouse tables; one query is fine.
    qs = DataWarehouseTable.objects.filter(team_id=team_id, deleted=False)
    for table in qs:
        column_refs: list[WarehouseColumnRef] = []
        columns = table.columns or {}
        for column_name, type_info in columns.items():
            if isinstance(type_info, dict):
                # Skip columns explicitly marked invalid by the schema scanner.
                if not type_info.get("valid", True):
                    continue
                raw_type = type_info.get("clickhouse")
            else:
                raw_type = type_info if isinstance(type_info, str) else None

            nullable = False
            clickhouse_type: str | None = raw_type
            if raw_type and raw_type.startswith("Nullable("):
                nullable = True
                clickhouse_type = raw_type[len("Nullable(") : -1]

            column_refs.append(
                WarehouseColumnRef(
                    name=column_name,
                    clickhouse_type=clickhouse_type,
                    nullable=nullable,
                )
            )

        refs.append(WarehouseTableRef(id=str(table.id), name=table.name, columns=column_refs))

    return refs
