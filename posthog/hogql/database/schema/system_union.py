"""Synthesize `system.tables` / `system.columns` / `system.relationships` rows from the in-process registry.

The catalog's three Postgres-backed tables are widened with a UNION ALL of
rows derived from `SystemTables().children` (and each PostgresTable's declared
`relationships=`) so every entry in `system.py` appears in HogQL queries
without any per-team Postgres seeding.

Identifiers are deterministic UUIDv5s keyed off `kind:name` so the three tables
remain referentially consistent — `system.columns.node_id` matches
`system.tables.id` for the same logical table, and `system.relationships`
references both.
"""

import uuid
from collections.abc import Callable, Iterator

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField, Table
from posthog.hogql.database.postgres_table import PostgresTable, build_function_call

# Arbitrary fixed namespace — only matters that it's stable across runs.
_SYSTEM_NAMESPACE = uuid.UUID("00000000-0000-0000-c47a-105000000000")

_SYSTEM_TABLE_KIND = "system_table"
_EPOCH_TS = "toDateTime64('1970-01-01 00:00:00', 6, 'UTC')"

# Mirrors the HogQL-field-class → short type-string mapping previously held in
# `products/catalog/backend/temporal/activities/enumerate.py`. Kept in sync
# with the type taxonomy in `posthog/hogql/database/models.py`.
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


def deterministic_table_id(name: str) -> uuid.UUID:
    return uuid.uuid5(_SYSTEM_NAMESPACE, f"system_table:{name}")


def deterministic_column_id(table_name: str, column_name: str) -> uuid.UUID:
    return uuid.uuid5(_SYSTEM_NAMESPACE, f"system_table:{table_name}:{column_name}")


def deterministic_relationship_id(
    source_table: str, source_column: str, target_table: str, target_column: str, kind: str
) -> uuid.UUID:
    key = f"rel:{source_table}.{source_column}->{target_table}.{target_column}:{kind}"
    return uuid.uuid5(_SYSTEM_NAMESPACE, key)


def _esc(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _normalize_hogql_type(field_descriptor: DatabaseField) -> str:
    cls_name = type(field_descriptor).__name__
    return _HOGQL_TYPE_MAP.get(cls_name, cls_name)


def _system_table_entries() -> Iterator[tuple[str, Table]]:
    """Yield (name, table) for every Table-instance child of SystemTables.

    Lazy import — `system.py` registers `SystemRegistryUnionTable` instances
    from this module, so the reverse direction must be deferred.
    """
    from posthog.hogql.database.schema.system import SystemTables

    for name, child in SystemTables().children.items():
        if isinstance(child.table, Table):
            yield name, child.table


def _build_synthesized_tables_select(team_id_param: str) -> str:
    rows: list[str] = []
    for name, _table in _system_table_entries():
        node_id = deterministic_table_id(name)
        rows.append(
            "SELECT "
            f"toUUID('{node_id}') AS id, "
            f"toInt32({team_id_param}) AS team_id, "
            f"'{_SYSTEM_TABLE_KIND}' AS kind, "
            f"{_esc(name)} AS name, "
            "CAST(NULL AS Nullable(String)) AS synthetic_description, "
            "CAST(NULL AS Nullable(String)) AS semantic_role, "
            "CAST(NULL AS Nullable(String)) AS business_domain, "
            "CAST([] AS Array(String)) AS tags, "
            f"{_EPOCH_TS} AS first_seen_at, "
            f"{_EPOCH_TS} AS last_seen_at, "
            "CAST(NULL AS Nullable(DateTime64(6, 'UTC'))) AS last_traversed_at, "
            "CAST(NULL AS Nullable(Float64)) AS confidence"
        )
    if not rows:
        # Should never happen in practice (SystemTables always has children),
        # but the UNION ALL syntax requires at least one SELECT on each side.
        return (
            "SELECT toUUID('00000000-0000-0000-0000-000000000000') AS id, toInt32(0) AS team_id, "
            "'' AS kind, '' AS name, CAST(NULL AS Nullable(String)) AS synthetic_description, "
            "CAST(NULL AS Nullable(String)) AS semantic_role, "
            "CAST(NULL AS Nullable(String)) AS business_domain, "
            "CAST([] AS Array(String)) AS tags, "
            f"{_EPOCH_TS} AS first_seen_at, {_EPOCH_TS} AS last_seen_at, "
            "CAST(NULL AS Nullable(DateTime64(6, 'UTC'))) AS last_traversed_at, "
            "CAST(NULL AS Nullable(Float64)) AS confidence WHERE 0"
        )
    return " UNION ALL ".join(rows)


def _build_synthesized_columns_select(team_id_param: str) -> str:
    rows: list[str] = []
    for table_name, table in _system_table_entries():
        node_id = deterministic_table_id(table_name)
        position = 0
        for field_name, descriptor in (table.fields or {}).items():
            if not isinstance(descriptor, DatabaseField):
                # Skip join targets, lazy tables, and expression aliases — same
                # logic as the deleted `enumerate.py:_fields_to_column_refs`.
                continue
            col_id = deterministic_column_id(table_name, field_name)
            ch_type = _normalize_hogql_type(descriptor)
            nullable_literal = "true" if descriptor.is_nullable() else "false"
            rows.append(
                "SELECT "
                f"toUUID('{col_id}') AS id, "
                f"toInt32({team_id_param}) AS team_id, "
                f"toUUID('{node_id}') AS node_id, "
                f"{_esc(field_name)} AS name, "
                f"toInt32({position}) AS position, "
                f"CAST({_esc(ch_type)} AS Nullable(String)) AS clickhouse_type, "
                "CAST(NULL AS Nullable(String)) AS hogql_type, "
                f"{nullable_literal} AS nullable, "
                "CAST(NULL AS Nullable(String)) AS synthetic_description, "
                "CAST(NULL AS Nullable(String)) AS semantic_type, "
                "CAST(NULL AS Nullable(String)) AS pii_class, "
                f"{_EPOCH_TS} AS last_seen_at, "
                "CAST(NULL AS Nullable(Float64)) AS confidence"
            )
            position += 1
    if not rows:
        return (
            "SELECT toUUID('00000000-0000-0000-0000-000000000000') AS id, toInt32(0) AS team_id, "
            "toUUID('00000000-0000-0000-0000-000000000000') AS node_id, '' AS name, "
            "toInt32(0) AS position, CAST(NULL AS Nullable(String)) AS clickhouse_type, "
            "CAST(NULL AS Nullable(String)) AS hogql_type, false AS nullable, "
            "CAST(NULL AS Nullable(String)) AS synthetic_description, "
            "CAST(NULL AS Nullable(String)) AS semantic_type, "
            "CAST(NULL AS Nullable(String)) AS pii_class, "
            f"{_EPOCH_TS} AS last_seen_at, "
            "CAST(NULL AS Nullable(Float64)) AS confidence WHERE 0"
        )
    return " UNION ALL ".join(rows)


def _build_synthesized_relationships_select(team_id_param: str) -> str:
    rows: list[str] = []
    for table_name, table in _system_table_entries():
        if not isinstance(table, PostgresTable):
            continue
        for rel in table.relationships:
            source_node = deterministic_table_id(table_name)
            target_node = deterministic_table_id(rel.to_table)
            source_col = deterministic_column_id(table_name, rel.from_column)
            target_col = deterministic_column_id(rel.to_table, rel.to_column)
            rel_id = deterministic_relationship_id(table_name, rel.from_column, rel.to_table, rel.to_column, rel.kind)
            rows.append(
                "SELECT "
                f"toUUID('{rel_id}') AS id, "
                f"toInt32({team_id_param}) AS team_id, "
                f"toUUID('{source_node}') AS source_node_id, "
                f"CAST(toUUID('{source_col}') AS Nullable(UUID)) AS source_column_id, "
                f"toUUID('{target_node}') AS target_node_id, "
                f"CAST(toUUID('{target_col}') AS Nullable(UUID)) AS target_column_id, "
                f"{_esc(rel.kind)} AS kind, "
                "toFloat64(1.0) AS confidence, "
                "'Declared in system.py' AS reasoning, "
                "'accepted' AS status, "
                f"{_EPOCH_TS} AS discovered_at, "
                f"{_EPOCH_TS} AS last_seen_at, "
                "CAST(NULL AS Nullable(UUID)) AS discovered_in_run_id"
            )
    if not rows:
        return (
            "SELECT toUUID('00000000-0000-0000-0000-000000000000') AS id, toInt32(0) AS team_id, "
            "toUUID('00000000-0000-0000-0000-000000000000') AS source_node_id, "
            "CAST(NULL AS Nullable(UUID)) AS source_column_id, "
            "toUUID('00000000-0000-0000-0000-000000000000') AS target_node_id, "
            "CAST(NULL AS Nullable(UUID)) AS target_column_id, "
            "'' AS kind, toFloat64(0.0) AS confidence, '' AS reasoning, '' AS status, "
            f"{_EPOCH_TS} AS discovered_at, {_EPOCH_TS} AS last_seen_at, "
            "CAST(NULL AS Nullable(UUID)) AS discovered_in_run_id WHERE 0"
        )
    return " UNION ALL ".join(rows)


_SYNTHESIZED_BUILDERS: dict[str, Callable[[str], str]] = {
    "tables": _build_synthesized_tables_select,
    "columns": _build_synthesized_columns_select,
    "relationships": _build_synthesized_relationships_select,
}


class SystemRegistryUnionTable(PostgresTable):
    """PostgresTable whose FROM-source is `(postgresql(...) UNION ALL synthesized rows)`.

    The synthesized side is generated at print time from the in-process
    `SystemTables` registry (and each PostgresTable's declared `relationships`),
    so the three catalog-backed system tables stay populated for every team
    without any Postgres writes.
    """

    synthesized_kind: str
    postgres_projection: list[str]

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        pg_source = build_function_call(self.postgres_table_name, context)
        left = f"SELECT {', '.join(self.postgres_projection)} FROM {pg_source}"
        team_id = context.team_id if context.team_id is not None else 0
        team_id_param = context.add_value(team_id)
        builder = _SYNTHESIZED_BUILDERS[self.synthesized_kind]
        right = builder(team_id_param)
        return f"({left} UNION ALL {right})"
