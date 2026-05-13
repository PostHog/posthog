"""Enumeration activities — read source-of-truth metadata and return refs.

Each `enumerate_*` activity returns a list of small `CatalogNodeRef` dataclasses
(one per table-like thing). The workflow chunks them and feeds them through
the shared `upsert_node_batch` activity. Splitting enumerate from upsert keeps
the read phase cheap and lets the workflow control batch sizing.

This module covers four sources today:
  - Imported data warehouse tables
  - Saved queries (derived views over the warehouse)
  - HogQL system tables (Postgres-backed metadata: cohorts, dashboards, ...)
  - PostHog-native tables (ClickHouse-backed product data: events, persons, ...)
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from temporalio import activity

from posthog.hogql.database.models import DatabaseField, Table
from posthog.hogql.database.schema.system import SystemTables

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


# --- HogQL system tables ------------------------------------------------------


@activity.defn
async def enumerate_system_tables(team_id: int) -> list[CatalogNodeRef]:
    """Return one ref per entry in posthog.hogql.database.schema.system.SystemTables.

    Content is team-independent (the registry is global), but the activity takes
    team_id for symmetry with the other enumerators — the upsert side scopes the
    catalog rows per team.
    """
    return await asyncio.to_thread(_enumerate_system_tables_sync)


def _enumerate_system_tables_sync() -> list[CatalogNodeRef]:
    refs: list[CatalogNodeRef] = []
    # SystemTables is a Pydantic model — `children` is a field default that
    # only materializes on an instance, not on the class itself.
    for name, child in SystemTables().children.items():
        if not isinstance(child.table, Table):
            continue
        refs.append(
            CatalogNodeRef(
                kind=CatalogNode.Kind.SYSTEM_TABLE,
                name=name,
                columns=_fields_to_column_refs(child.table.fields or {}),
            )
        )
    return refs


def _fields_to_column_refs(fields: dict[str, Any]) -> list[CatalogColumnRef]:
    """Turn a HogQL Table.fields dict into CatalogColumnRefs.

    Skips non-`DatabaseField` entries (joins, lazy tables, expression aliases) —
    those aren't columns the agent can `SELECT`.
    """
    refs: list[CatalogColumnRef] = []
    for field_name, descriptor in fields.items():
        if not isinstance(descriptor, DatabaseField):
            continue
        refs.append(
            CatalogColumnRef(
                name=field_name,
                clickhouse_type=_normalize_hogql_type(descriptor),
                nullable=descriptor.is_nullable(),
            )
        )
    return refs


def _normalize_hogql_type(field_descriptor: DatabaseField) -> str:
    """Derive a short ClickHouse-flavoured type string from a HogQL DatabaseField."""
    cls_name = type(field_descriptor).__name__
    return _HOGQL_TYPE_MAP.get(cls_name, cls_name)


_HOGQL_TYPE_MAP: dict[str, str] = {
    "IntegerDatabaseField": "Int",
    "FloatDatabaseField": "Float",
    "DecimalDatabaseField": "Decimal",
    "StringDatabaseField": "String",
    "UnknownDatabaseField": "Unknown",
    "StringJSONDatabaseField": "JSON",
    "StructDatabaseField": "Struct",
    "StringArrayDatabaseField": "Array(String)",
    "FloatArrayDatabaseField": "Array(Float)",
    "DateDatabaseField": "Date",
    "DateTimeDatabaseField": "DateTime",
    "BooleanDatabaseField": "Boolean",
    "UUIDDatabaseField": "UUID",
}


# --- PostHog-native ClickHouse tables ----------------------------------------

# Small curated set of the core product tables an analyst-style agent reaches
# for. Not exhaustive — the goal is to give Phase 2 something to join against
# (e.g. warehouse.users.email → persons.properties.$email). Expand as new
# join patterns emerge.
_POSTHOG_TABLE_REFS: list[CatalogNodeRef] = [
    CatalogNodeRef(
        kind=CatalogNode.Kind.POSTHOG_TABLE,
        name="events",
        columns=[
            CatalogColumnRef("uuid", "UUID", False),
            CatalogColumnRef("event", "String", False),
            CatalogColumnRef("properties", "JSON", False),
            CatalogColumnRef("timestamp", "DateTime", False),
            CatalogColumnRef("team_id", "Int", False),
            CatalogColumnRef("distinct_id", "String", False),
            CatalogColumnRef("person_id", "UUID", True),
            CatalogColumnRef("session_id", "String", True),
        ],
    ),
    CatalogNodeRef(
        kind=CatalogNode.Kind.POSTHOG_TABLE,
        name="persons",
        columns=[
            CatalogColumnRef("id", "UUID", False),
            CatalogColumnRef("team_id", "Int", False),
            CatalogColumnRef("properties", "JSON", False),
            CatalogColumnRef("created_at", "DateTime", False),
            CatalogColumnRef("is_identified", "Boolean", False),
        ],
    ),
    CatalogNodeRef(
        kind=CatalogNode.Kind.POSTHOG_TABLE,
        name="sessions",
        columns=[
            CatalogColumnRef("session_id", "String", False),
            CatalogColumnRef("team_id", "Int", False),
            CatalogColumnRef("distinct_id", "String", False),
            CatalogColumnRef("$start_timestamp", "DateTime", True),
            CatalogColumnRef("$end_timestamp", "DateTime", True),
            CatalogColumnRef("$event_count", "Int", True),
        ],
    ),
    CatalogNodeRef(
        kind=CatalogNode.Kind.POSTHOG_TABLE,
        name="groups",
        columns=[
            CatalogColumnRef("team_id", "Int", False),
            CatalogColumnRef("group_type_index", "Int", False),
            CatalogColumnRef("group_key", "String", False),
            CatalogColumnRef("group_properties", "JSON", False),
            CatalogColumnRef("created_at", "DateTime", False),
        ],
    ),
]


@activity.defn
async def enumerate_posthog_tables(team_id: int) -> list[CatalogNodeRef]:
    """Return the curated list of PostHog-native product tables.

    Team-independent content — the activity takes team_id for symmetry, but
    the registry is the same across teams. Per-team scoping happens at upsert
    time on CatalogNode.team_id.
    """
    # Return a copy so callers can mutate without affecting the module-level list.
    return [CatalogNodeRef(kind=r.kind, name=r.name, columns=list(r.columns), id=r.id) for r in _POSTHOG_TABLE_REFS]
