"""Enumeration activities — read source-of-truth metadata and return refs.

Each `enumerate_*` activity returns a list of small `CatalogNodeRef` dataclasses
(one per table-like thing). The workflow chunks them and feeds them through
the shared `upsert_node_batch` activity. Splitting enumerate from upsert keeps
the read phase cheap and lets the workflow control batch sizing.

This module covers the dynamic-content sources:
  - Imported data warehouse tables
  - Saved queries (derived views over the warehouse)

The HogQL system tables and PostHog-native ClickHouse tables are exposed
directly through `system.tables` / `system.columns` / `system.relationships`
via a UNION on the HogQL side (see `posthog/hogql/database/schema/system_union.py`).
No per-team Postgres seeding is required for them.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from temporalio import activity

from products.catalog.backend.models import CatalogNode
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.table import DataWarehouseTable


@dataclass
class CatalogColumnRef:
    """Lightweight column descriptor — what the catalog needs to materialize a CatalogColumn."""

    name: str
    clickhouse_type: str | None
    nullable: bool


@dataclass
class CatalogNodeRef:
    """One table-shaped node to upsert.

    `id` is set only for kinds that bind to a backing Django row via the GFK on
    CatalogNode (warehouse_table → DataWarehouseTable, saved_query →
    DataWarehouseSavedQuery). System and posthog tables leave it empty since
    those nodes are identifier-only.
    """

    kind: str  # CatalogNode.Kind value
    name: str
    columns: list[CatalogColumnRef] = field(default_factory=list)
    id: str | None = None  # UUID string of the backing row, when applicable


# --- Warehouse tables ---------------------------------------------------------


@activity.defn
async def enumerate_warehouse_tables(team_id: int) -> list[CatalogNodeRef]:
    """Return refs for every non-deleted warehouse table belonging to the team."""
    return await asyncio.to_thread(_enumerate_warehouse_tables_sync, team_id)


def _enumerate_warehouse_tables_sync(team_id: int) -> list[CatalogNodeRef]:
    refs: list[CatalogNodeRef] = []
    qs = DataWarehouseTable.objects.filter(team_id=team_id, deleted=False)
    for table in qs:
        refs.append(
            CatalogNodeRef(
                kind=CatalogNode.Kind.WAREHOUSE_TABLE,
                name=table.name,
                columns=_parse_warehouse_columns(table.columns or {}),
                id=str(table.id),
            )
        )
    return refs


def _parse_warehouse_columns(columns: dict[str, Any]) -> list[CatalogColumnRef]:
    """DataWarehouseTable / SavedQuery `columns` is a dict {col: type_info}.

    type_info is either a plain string (old style) or
    `{"clickhouse": "...", "valid": bool}` (current style). Mirror the parsing
    in `DataWarehouseTable.hogql_definition`.
    """
    parsed: list[CatalogColumnRef] = []
    for column_name, type_info in columns.items():
        if isinstance(type_info, dict):
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

        parsed.append(CatalogColumnRef(name=column_name, clickhouse_type=clickhouse_type, nullable=nullable))
    return parsed


# --- Saved queries ------------------------------------------------------------


@activity.defn
async def enumerate_saved_queries(team_id: int) -> list[CatalogNodeRef]:
    """Return refs for every non-deleted saved query belonging to the team."""
    return await asyncio.to_thread(_enumerate_saved_queries_sync, team_id)


def _enumerate_saved_queries_sync(team_id: int) -> list[CatalogNodeRef]:
    refs: list[CatalogNodeRef] = []
    qs = DataWarehouseSavedQuery.objects.filter(team_id=team_id, deleted=False)
    for saved_query in qs:
        refs.append(
            CatalogNodeRef(
                kind=CatalogNode.Kind.SAVED_QUERY,
                name=saved_query.name,
                # Saved query columns use the same JSON shape as warehouse tables —
                # the schema scanner writes both.
                columns=_parse_warehouse_columns(saved_query.columns or {}),
                id=str(saved_query.id),
            )
        )
    return refs


# HogQL system tables and PostHog-native ClickHouse tables used to be
# enumerated here and seeded as `CatalogNode` rows per team. They are now
# exposed directly through the `system.tables` / `system.columns` /
# `system.relationships` UNION (see `posthog/hogql/database/schema/system_union.py`)
# so no per-team Postgres seeding is required.
