"""Diff engine: compare desired state against current live schema.

Produces a list of StateDiff objects, each representing a single DDL operation
(CREATE, ALTER, DROP, recreate) with the SQL to execute, target node roles,
and dependency ordering.

The diff respects ClickHouse ecosystem rules:
- DROP MV before altering source tables
- CREATE local tables before Distributed tables
- CREATE Kafka tables before MVs
- ALTER all ecosystem tables when adding a column (sharded + writable + readable)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.conf import settings as django_settings

from posthog.clickhouse.migration_tools.desired_state import ColumnDef, DesiredState, DesiredTable
from posthog.clickhouse.migration_tools.schema_introspect import TableSchema

# Sentinel value used in schema YAML to indicate the value should come from Django settings
_FROM_SETTINGS_SENTINEL = "__from_settings__"

# Map of YAML setting keys to Django settings attributes
_SETTINGS_RESOLUTION: dict[str, str] = {
    "kafka_broker_list": "KAFKA_HOSTS_FOR_CLICKHOUSE",
}


def _resolve_setting(key: str) -> str:
    """Resolve a __from_settings__ sentinel to its Django settings value."""
    attr = _SETTINGS_RESOLUTION.get(key)
    if attr:
        val = getattr(django_settings, attr, None)
        if val:
            return ",".join(val) if isinstance(val, list) else str(val)
    # Fallback for local dev
    return "kafka:9092"


@dataclass
class StateDiff:
    # "create", "alter_add_column", "alter_drop_column",
    # "alter_modify_column", "drop", "recreate_mv", "recreate"
    action: str
    table: str
    detail: str
    sql: str
    node_roles: list[str]
    sharded: bool = False
    is_alter_on_replicated_table: bool = False
    depends_on: list[str] = field(default_factory=list)


# Engine tier determines creation order and helps classify table types
_ENGINE_TIER: dict[str, int] = {
    "kafka": 0,
    "mergetree": 1,
    "replacingmergetree": 1,
    "replicatedmergetree": 1,
    "replicatedreplacingmergetree": 1,
    "collapsingmergetree": 1,
    "replicatedcollapsingmergetree": 1,
    "versionedcollapsingmergetree": 1,
    "replicatedversionedcollapsingmergetree": 1,
    "summingmergetree": 1,
    "replicatedsummingmergetree": 1,
    "aggregatingmergetree": 1,
    "replicatedaggregatingmergetree": 1,
    "distributed": 2,
    "materializedview": 3,
    "dictionary": 3,
}


def _engine_tier(engine: str) -> int:
    return _ENGINE_TIER.get(engine.lower(), 1)


def _is_mergetree(engine: str) -> bool:
    return "mergetree" in engine.lower()


def _is_distributed(engine: str) -> bool:
    return engine.lower() == "distributed"


def _is_mv(engine: str) -> bool:
    return engine.lower() == "materializedview"


def _is_kafka(engine: str) -> bool:
    return engine.lower() == "kafka"


def _columns_sql(columns: list[ColumnDef]) -> str:
    parts = []
    for col in columns:
        line = f"    {col.name} {col.type}"
        if col.default_expression:
            kind = col.default_kind or "DEFAULT"
            line += f" {kind} {col.default_expression}"
        if col.codec:
            line += f" CODEC({col.codec})"
        parts.append(line)
    return ",\n".join(parts)


def _generate_create_sql(
    table: DesiredTable,
    database: str,
    cluster: str,
) -> str:
    """Generate CREATE TABLE/VIEW SQL from a DesiredTable."""
    cols = _columns_sql(table.columns)

    if _is_mv(table.engine):
        target = table.target or ""
        select = (table.select or "SELECT * FROM ???").replace("{{ database }}", database)
        return f"CREATE MATERIALIZED VIEW IF NOT EXISTS {database}.{table.name}\nTO {database}.{target}\nAS {select}"

    if _is_distributed(table.engine):
        source = table.source or ""
        sharding = table.sharding_key or "rand()"
        return (
            f"CREATE TABLE IF NOT EXISTS {database}.{table.name}\n"
            f"(\n{cols}\n"
            f") ENGINE = Distributed('{cluster}', '{database}', '{source}', {sharding})"
        )

    if _is_kafka(table.engine):
        settings_lines = []
        if table.settings:
            for k, v in table.settings.items():
                resolved = _resolve_setting(k) if str(v) == _FROM_SETTINGS_SENTINEL else v
                settings_lines.append(f"    {k} = '{resolved}'")
        settings_block = ",\n".join(settings_lines)
        return (
            f"CREATE TABLE IF NOT EXISTS {database}.{table.name}\n"
            f"(\n{cols}\n"
            f") ENGINE = Kafka()\n"
            f"SETTINGS\n{settings_block}"
        )

    # MergeTree family
    engine_call = f"{table.engine}()"
    partition = f"\nPARTITION BY {table.partition_by}" if table.partition_by else ""
    order_by = f"\nORDER BY ({', '.join(table.order_by)})" if table.order_by else ""

    return (
        f"CREATE TABLE IF NOT EXISTS {database}.{table.name}\n(\n{cols}\n) ENGINE = {engine_call}{partition}{order_by}"
    )


def _normalize_mv_select(sql: str) -> str:
    """Normalize MV SELECT SQL for semantic comparison.

    Collapses whitespace, lowercases SQL keywords, strips comments.
    Does NOT parse the SQL — catches the common false-positive cases:
    indentation changes, trailing newlines, keyword casing.
    """
    import re

    # Remove comments
    s = re.sub(r"--[^\n]*\n", " ", sql)
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s)
    # Normalize keyword case
    keywords = [
        "SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY", "HAVING",
        "JOIN", "LEFT JOIN", "INNER JOIN", "AS", "AND", "OR", "NOT",
        "IN", "IS", "NULL", "LIMIT", "OFFSET", "UNION", "ALL",
        "CASE", "WHEN", "THEN", "ELSE", "END",
    ]
    for kw in keywords:
        s = re.sub(rf"\b{kw}\b", kw.lower(), s, flags=re.IGNORECASE)
    return s.strip()


def diff_state(
    desired: DesiredState,
    current: dict[str, TableSchema],
    database: str | None = None,
    cluster: str | None = None,
) -> list[StateDiff]:
    """Compare desired state against current schema and produce a list of diffs.

    Returns StateDiff objects sorted in dependency order (drops before creates,
    local before distributed, kafka before MV).
    """
    db = database or desired.database
    cl = cluster or desired.cluster

    drops: list[StateDiff] = []
    creates: list[StateDiff] = []
    alters: list[StateDiff] = []
    recreates: list[StateDiff] = []

    desired_names = set(desired.tables.keys())
    current_names = set(current.keys())

    # Tables to drop (in current but not in desired)
    for table_name in sorted(current_names - desired_names):
        current_table = current[table_name]
        drops.append(
            StateDiff(
                action="drop",
                table=table_name,
                detail=f"Table {table_name} exists but is not in desired state",
                sql=f"DROP TABLE IF EXISTS {db}.{table_name}",
                node_roles=["ALL"],
            )
        )

    # Tables to create (in desired but not in current)
    for table_name in sorted(desired_names - current_names):
        desired_table = desired.tables[table_name]
        deps = []
        if _is_distributed(desired_table.engine) and desired_table.source:
            deps.append(desired_table.source)
        if _is_mv(desired_table.engine):
            if desired_table.target:
                deps.append(desired_table.target)

        creates.append(
            StateDiff(
                action="create",
                table=table_name,
                detail=f"Create {desired_table.engine} table {table_name}",
                sql=_generate_create_sql(desired_table, db, cl),
                node_roles=desired_table.on_nodes,
                sharded=desired_table.sharded,
                depends_on=deps,
            )
        )

    # Tables that exist in both — check for changes
    for table_name in sorted(desired_names & current_names):
        desired_table = desired.tables[table_name]
        current_table = current[table_name]

        # Engine mismatch → recreate
        if desired_table.engine.lower() != current_table.engine.lower():
            if _is_mv(desired_table.engine) or _is_mv(current_table.engine):
                recreates.append(
                    StateDiff(
                        action="recreate_mv",
                        table=table_name,
                        detail=(
                            f"Recreate MV {table_name} "
                            f"(engine changed: {current_table.engine} -> {desired_table.engine})"
                        ),
                        sql=(f"DROP TABLE IF EXISTS {db}.{table_name};\n{_generate_create_sql(desired_table, db, cl)}"),
                        node_roles=desired_table.on_nodes,
                        depends_on=[desired_table.target] if desired_table.target else [],
                    )
                )
            else:
                recreates.append(
                    StateDiff(
                        action="recreate",
                        table=table_name,
                        detail=(
                            f"Recreate {table_name} (engine changed: {current_table.engine} -> {desired_table.engine})"
                        ),
                        sql=(f"DROP TABLE IF EXISTS {db}.{table_name};\n{_generate_create_sql(desired_table, db, cl)}"),
                        node_roles=desired_table.on_nodes,
                        sharded=desired_table.sharded,
                    )
                )
            continue

        # Structural field comparisons (order_by, partition_by, sharding_key, source, target, settings)
        structural_recreate = False
        structural_details: list[str] = []

        if _is_mergetree(desired_table.engine):
            # ORDER BY
            if desired_table.order_by:
                current_sorting = current_table.sorting_key
                desired_sorting = ", ".join(desired_table.order_by)
                if current_sorting and current_sorting != desired_sorting:
                    structural_details.append(f"ORDER BY changed: {current_sorting} -> {desired_sorting}")
                    structural_recreate = True
            # PARTITION BY
            if desired_table.partition_by:
                if current_table.partition_key and current_table.partition_key != desired_table.partition_by:
                    structural_details.append(
                        f"PARTITION BY changed: {current_table.partition_key} -> {desired_table.partition_by}"
                    )
                    structural_recreate = True

        if _is_distributed(desired_table.engine):
            # sharding_key — requires recreate
            if desired_table.sharding_key and current_table.engine_full:
                if desired_table.sharding_key not in current_table.engine_full:
                    structural_details.append(f"sharding_key changed (desired: {desired_table.sharding_key})")
                    structural_recreate = True
            # source — the local table backing the Distributed table
            if desired_table.source and current_table.engine_full:
                if desired_table.source not in current_table.engine_full:
                    structural_details.append(f"source table changed (desired: {desired_table.source})")
                    structural_recreate = True

        if _is_mv(desired_table.engine):
            # target — the destination table for the MV
            if desired_table.target and current_table.engine_full:
                if desired_table.target not in current_table.engine_full:
                    structural_details.append(f"MV target changed (desired: {desired_table.target})")
                    structural_recreate = True

        if _is_kafka(desired_table.engine):
            # Kafka settings (broker_list, topic_list, group_name, format) — requires recreate
            if desired_table.settings and current_table.engine_full:
                for setting_key, setting_val in desired_table.settings.items():
                    resolved = (
                        _resolve_setting(setting_key) if str(setting_val) == _FROM_SETTINGS_SENTINEL else str(setting_val)
                    )
                    if resolved not in current_table.engine_full:
                        structural_details.append(f"Kafka setting '{setting_key}' changed (desired: {resolved})")
                        structural_recreate = True

        if structural_recreate:
            detail_str = "; ".join(structural_details)
            if _is_mv(desired_table.engine):
                recreates.append(
                    StateDiff(
                        action="recreate_mv",
                        table=table_name,
                        detail=f"Recreate MV {table_name} ({detail_str})",
                        sql=f"DROP TABLE IF EXISTS {db}.{table_name};\n{_generate_create_sql(desired_table, db, cl)}",
                        node_roles=desired_table.on_nodes,
                        depends_on=[desired_table.target] if desired_table.target else [],
                    )
                )
            else:
                recreates.append(
                    StateDiff(
                        action="recreate",
                        table=table_name,
                        detail=f"Recreate {table_name} ({detail_str})",
                        sql=f"DROP TABLE IF EXISTS {db}.{table_name};\n{_generate_create_sql(desired_table, db, cl)}",
                        node_roles=desired_table.on_nodes,
                        sharded=desired_table.sharded,
                    )
                )
            continue

        # Column default/codec changes — ALTER MODIFY COLUMN (checked during column comparison below)

        # For MVs, compare SELECT if both sides have it
        if _is_mv(desired_table.engine) and desired_table.select:
            current_select = current_table.as_select if hasattr(current_table, "as_select") else ""
            if current_select and _normalize_mv_select(current_select) != _normalize_mv_select(desired_table.select):
                drops.append(
                    StateDiff(
                        action="drop",
                        table=table_name,
                        detail=f"Drop MV {table_name} (SELECT changed — will recreate)",
                        sql=f"DROP TABLE IF EXISTS {db}.{table_name}",
                        node_roles=desired_table.on_nodes,
                    )
                )
                creates.append(
                    StateDiff(
                        action="create",
                        table=table_name,
                        detail=f"Recreate MV {table_name} with updated SELECT",
                        sql=_generate_create_sql(desired_table, db, cl),
                        node_roles=desired_table.on_nodes,
                    )
                )
            elif not current_select:
                import logging

                logging.getLogger("migrations").warning(
                    "MV %s: SELECT comparison not possible (as_select not available from host). "
                    "Verify manually with 'ch_migrate schema'.",
                    table_name,
                )

        # Column comparison
        desired_cols = {c.name: c for c in desired_table.columns}
        current_cols = {c.name: c for c in current_table.columns}

        # Kafka/Dictionary engines don't support ALTER — recreate instead
        if desired_table.engine.lower() in ("kafka", "dictionary") and desired_cols != current_cols:
            drops.append(
                StateDiff(
                    action="drop",
                    table=table_name,
                    detail=f"Drop {desired_table.engine} table {table_name} (recreate for column change)",
                    sql=f"DROP TABLE IF EXISTS {db}.{table_name}",
                    node_roles=desired_table.on_nodes,
                )
            )
            creates.append(
                StateDiff(
                    action="create",
                    table=table_name,
                    detail=f"Recreate {desired_table.engine} table {table_name} with updated columns",
                    sql=_generate_create_sql(desired_table, db, cl),
                    node_roles=desired_table.on_nodes,
                )
            )
            continue

        # Skip column diffing for MVs (columns are derived from SELECT)
        if _is_mv(desired_table.engine):
            continue

        is_replicated = _is_mergetree(desired_table.engine) and "replicated" in desired_table.engine.lower()

        # Missing columns (in desired but not in current) → ADD COLUMN
        for col_name in sorted(set(desired_cols.keys()) - set(current_cols.keys())):
            col = desired_cols[col_name]
            default_clause = ""
            if col.default_expression:
                kind = col.default_kind or "DEFAULT"
                default_clause = f" {kind} {col.default_expression}"
            alters.append(
                StateDiff(
                    action="alter_add_column",
                    table=table_name,
                    detail=f"Add column {col_name} {col.type} to {table_name}",
                    sql=f"ALTER TABLE {db}.{table_name} ADD COLUMN IF NOT EXISTS {col_name} {col.type}{default_clause}",
                    node_roles=desired_table.on_nodes,
                    sharded=desired_table.sharded,
                    is_alter_on_replicated_table=is_replicated,
                )
            )

        # Extra columns (in current but not in desired) → DROP COLUMN
        for col_name in sorted(set(current_cols.keys()) - set(desired_cols.keys())):
            alters.append(
                StateDiff(
                    action="alter_drop_column",
                    table=table_name,
                    detail=f"Drop column {col_name} from {table_name}",
                    sql=f"ALTER TABLE {db}.{table_name} DROP COLUMN IF EXISTS {col_name}",
                    node_roles=desired_table.on_nodes,
                    sharded=desired_table.sharded,
                    is_alter_on_replicated_table=is_replicated,
                )
            )

        # Type mismatches → MODIFY COLUMN
        for col_name in sorted(set(desired_cols.keys()) & set(current_cols.keys())):
            desired_col = desired_cols[col_name]
            current_col = current_cols[col_name]
            if desired_col.type != current_col.type:
                alters.append(
                    StateDiff(
                        action="alter_modify_column",
                        table=table_name,
                        detail=(
                            f"Modify column {col_name} from {current_col.type} to {desired_col.type} on {table_name}"
                        ),
                        sql=f"ALTER TABLE {db}.{table_name} MODIFY COLUMN {col_name} {desired_col.type}",
                        node_roles=desired_table.on_nodes,
                        sharded=desired_table.sharded,
                        is_alter_on_replicated_table=is_replicated,
                    )
                )
                continue

            # Default kind/expression changes → MODIFY COLUMN
            desired_default = f"{desired_col.default_kind} {desired_col.default_expression}".strip()
            current_default = f"{current_col.default_kind} {current_col.default_expression}".strip()
            desired_codec = desired_col.codec if hasattr(desired_col, "codec") else ""
            current_codec = ""  # system.columns doesn't expose codec directly

            if desired_default and desired_default != current_default:
                kind = desired_col.default_kind or "DEFAULT"
                modify_clause = f"{col_name} {desired_col.type} {kind} {desired_col.default_expression}"
                alters.append(
                    StateDiff(
                        action="alter_modify_column",
                        table=table_name,
                        detail=(
                            f"Modify column {col_name} default on {table_name}: "
                            f"{current_default!r} -> {desired_default!r}"
                        ),
                        sql=f"ALTER TABLE {db}.{table_name} MODIFY COLUMN {modify_clause}",
                        node_roles=desired_table.on_nodes,
                        sharded=desired_table.sharded,
                        is_alter_on_replicated_table=is_replicated,
                    )
                )

    # Sort by dependency order:
    # 1. Drop MVs first (tier 3 drops first)
    # 2. Drop distributed (tier 2)
    # 3. Drop local/kafka (tier 1/0)
    # 4. Alters on local tables
    # 5. Alters on distributed tables
    # 6. Creates in tier order (kafka=0, local=1, distributed=2, MV=3)
    # 7. Recreates (MV recreates last)

    def _drop_sort_key(d: StateDiff) -> tuple[int, str]:
        # Higher tier drops first (MVs before distributed before local)
        tier = 3 - _engine_tier(current.get(d.table, TableSchema(name=d.table, engine="")).engine)
        return (tier, d.table)

    def _alter_sort_key(d: StateDiff) -> tuple[int, str]:
        table = desired.tables.get(d.table)
        tier = _engine_tier(table.engine) if table else 1
        return (tier, d.table)

    def _create_sort_key(d: StateDiff) -> tuple[int, str]:
        table = desired.tables.get(d.table)
        tier = _engine_tier(table.engine) if table else 1
        return (tier, d.table)

    drops.sort(key=_drop_sort_key)
    alters.sort(key=_alter_sort_key)
    creates.sort(key=_create_sort_key)

    return drops + alters + creates + recreates


def detect_orphans(
    desired_states: list[DesiredState],
    current: dict[str, TableSchema],
    exclude_patterns: list[str] | None = None,
) -> list[str]:
    """Find tables in current schema that are not declared in any YAML.

    Returns a sorted list of orphan table names. This is read-only — it
    only reports, it does not drop anything.
    """
    declared: set[str] = set()
    for ds in desired_states:
        declared.update(ds.tables.keys())

    default_exclude = {"infi_clickhouse_orm_migrations", "clickhouse_schema_migrations"}
    exclude = default_exclude | set(exclude_patterns or [])

    orphans = []
    for name in current:
        if name in declared or name in exclude:
            continue
        engine = current[name].engine.lower()
        if engine in ("view", "join"):
            continue
        if name.startswith("_tmp") or name.startswith("pending_deletes"):
            continue
        orphans.append(name)

    return sorted(orphans)
