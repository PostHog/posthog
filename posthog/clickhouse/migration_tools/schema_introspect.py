"""Live schema introspection and drift detection. Shared by both migration approaches."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from posthog.clickhouse.cluster import ClickhouseCluster, HostInfo


@dataclass
class ColumnSchema:
    name: str
    type: str
    default_kind: str = ""
    default_expression: str = ""
    position: int = 0


@dataclass
class TableSchema:
    name: str
    engine: str
    engine_full: str = ""
    sorting_key: str = ""
    partition_key: str = ""
    primary_key: str = ""
    as_select: str = ""  # MV SELECT statement (from system.tables.as_select)
    columns: list[ColumnSchema] = field(default_factory=list)
    # Dictionary-only metadata, populated from system.dictionaries for rows
    # where engine == "Dictionary". Dictionaries don't support ALTER so drift
    # detection must be fine-grained: any change in source/layout/lifetime
    # forces DROP + CREATE. The raw source string is kept as a fallback for
    # substring matching — the decomposed fields cover common recreate cases
    # (type, lifetime bounds), while engine_full covers per-param changes
    # that layout/source type alone miss.
    dict_source_type: str = ""  # e.g. "ClickHouse", "HTTP", "MySQL"
    dict_source_raw: str = ""  # full SOURCE string as rendered by CH
    dict_layout_type: str = ""  # e.g. "HASHED", "COMPLEX_KEY_HASHED"
    dict_lifetime_min: int = 0
    dict_lifetime_max: int = 0


@dataclass
class SchemaDiff:
    table: str
    column: str | None
    diff_type: (
        str  # missing_table, extra_table, missing_column, extra_column, type_mismatch, engine_mismatch, key_mismatch
    )
    host: str = ""
    expected: str = ""
    actual: str = ""


def dump_schema(client: Any, database: str) -> dict[str, TableSchema]:
    """Query a single ClickHouse host for its current schema state."""
    tables_rows = client.execute(
        "SELECT name, engine, engine_full, sorting_key, partition_key, primary_key, as_select "
        "FROM system.tables WHERE database = %(database)s",
        {"database": database},
    )

    columns_rows = client.execute(
        "SELECT table, name, type, default_kind, default_expression, position "
        "FROM system.columns WHERE database = %(database)s "
        "ORDER BY table, position",
        {"database": database},
    )

    schema: dict[str, TableSchema] = {}
    for name, engine, engine_full, sorting_key, partition_key, primary_key, as_select in tables_rows:
        schema[name] = TableSchema(
            name=name,
            engine=engine,
            engine_full=engine_full,
            sorting_key=sorting_key,
            partition_key=partition_key,
            primary_key=primary_key,
            as_select=as_select or "",
        )

    for table, col_name, col_type, default_kind, default_expression, position in columns_rows:
        if table in schema:
            schema[table].columns.append(
                ColumnSchema(
                    name=col_name,
                    type=col_type,
                    default_kind=default_kind,
                    default_expression=default_expression,
                    position=position,
                )
            )

    # Enrich Dictionary rows with system.dictionaries metadata. Dictionaries
    # show up in system.tables with engine="Dictionary" but don't expose
    # SOURCE/LAYOUT/LIFETIME there — those live in system.dictionaries.
    # Without this enrichment, the recreate check in state_diff falls back
    # to scanning engine_full (which handles lifetime/layout substring
    # matches) but can't compare source types directly or report structured
    # lifetime drift (e.g. 300/600 -> 3000/3600).
    dump_dictionaries(client, database, schema)

    return schema


def dump_dictionaries(client: Any, database: str, schema: dict[str, TableSchema]) -> None:
    """Query system.dictionaries and enrich existing TableSchema entries.

    Mutates ``schema`` in place. Rows without a corresponding system.tables
    entry are silently dropped — this keeps the function safe to call
    against hosts where a dictionary was created outside the managed set,
    without synthesizing bogus TableSchema rows that downstream diff logic
    would misinterpret as real tables.
    """
    rows = client.execute(
        "SELECT name, source, type, lifetime_min, lifetime_max FROM system.dictionaries WHERE database = %(database)s",
        {"database": database},
    )
    for name, source, layout_type, lifetime_min, lifetime_max in rows:
        table = schema.get(name)
        if table is None:
            # Dictionary in system.dictionaries but not system.tables — can
            # happen mid-create or mid-drop; skip rather than inventing a
            # TableSchema downstream passes would mishandle.
            continue
        # CH renders source as "ClickHouse: posthog.events" — split on the
        # first colon to get the source kind. The full string is kept in
        # dict_source_raw for fallback substring matching.
        if ":" in source:
            source_type, _, _ = source.partition(":")
            table.dict_source_type = source_type.strip()
        else:
            table.dict_source_type = source.strip()
        table.dict_source_raw = source
        table.dict_layout_type = (layout_type or "").upper()
        table.dict_lifetime_min = int(lifetime_min or 0)
        table.dict_lifetime_max = int(lifetime_max or 0)


def dump_schema_all_hosts(cluster: ClickhouseCluster, database: str) -> dict[HostInfo, dict[str, TableSchema]]:
    """Run dump_schema on every host in the cluster."""

    def _dump(client: Any) -> dict[str, TableSchema]:
        return dump_schema(client, database)

    futures = cluster.map_all_hosts(_dump)
    return futures.result()


def compare_schemas(
    expected: dict[str, TableSchema],
    actual: dict[str, TableSchema],
) -> list[SchemaDiff]:
    """Compare two schema dumps and return differences."""
    diffs: list[SchemaDiff] = []

    expected_names = set(expected.keys())
    actual_names = set(actual.keys())

    for table in sorted(expected_names - actual_names):
        diffs.append(SchemaDiff(table=table, column=None, diff_type="missing_table", expected=table, actual=""))

    for table in sorted(actual_names - expected_names):
        diffs.append(SchemaDiff(table=table, column=None, diff_type="extra_table", expected="", actual=table))

    for table in sorted(expected_names & actual_names):
        exp_table = expected[table]
        act_table = actual[table]

        # Engine mismatch
        if exp_table.engine != act_table.engine:
            diffs.append(
                SchemaDiff(
                    table=table,
                    column=None,
                    diff_type="engine_mismatch",
                    expected=exp_table.engine,
                    actual=act_table.engine,
                )
            )

        # Sorting key mismatch
        if exp_table.sorting_key != act_table.sorting_key:
            diffs.append(
                SchemaDiff(
                    table=table,
                    column=None,
                    diff_type="key_mismatch",
                    expected=f"sorting_key={exp_table.sorting_key}",
                    actual=f"sorting_key={act_table.sorting_key}",
                )
            )

        # Partition key mismatch — distinct diff_type so downstream filtering
        # can treat partitioning drift separately from sort-key drift.
        if exp_table.partition_key != act_table.partition_key:
            diffs.append(
                SchemaDiff(
                    table=table,
                    column=None,
                    diff_type="partition_key_mismatch",
                    expected=f"partition_key={exp_table.partition_key}",
                    actual=f"partition_key={act_table.partition_key}",
                )
            )

        # Primary key mismatch. Separate from sorting_key: ClickHouse lets
        # PRIMARY KEY be a prefix of ORDER BY with different semantics
        # (index granularity marks), so drift in one doesn't imply the other.
        if exp_table.primary_key != act_table.primary_key:
            diffs.append(
                SchemaDiff(
                    table=table,
                    column=None,
                    diff_type="primary_key_mismatch",
                    expected=f"primary_key={exp_table.primary_key}",
                    actual=f"primary_key={act_table.primary_key}",
                )
            )

        # engine_full captures engine args (zk path, replica name, replacement
        # version column, distributed cluster args, etc.) that aren't in
        # `engine` alone. Only compare when both sides populate it — older CH
        # versions or system tables may leave it empty.
        if exp_table.engine_full and act_table.engine_full and exp_table.engine_full != act_table.engine_full:
            diffs.append(
                SchemaDiff(
                    table=table,
                    column=None,
                    diff_type="engine_full_mismatch",
                    expected=exp_table.engine_full,
                    actual=act_table.engine_full,
                )
            )

        # Dictionary metadata drift (host-to-host). Layout type, source type
        # and lifetime windows should be identical across hosts in the same
        # role group — when they aren't, a dictionary was recreated with
        # different config on one host. Raw source isn't compared because CH
        # can render it with host-local DSN strings that vary benignly.
        if exp_table.engine == "Dictionary" and act_table.engine == "Dictionary":
            if exp_table.dict_layout_type != act_table.dict_layout_type:
                diffs.append(
                    SchemaDiff(
                        table=table,
                        column=None,
                        diff_type="dict_layout_mismatch",
                        expected=exp_table.dict_layout_type,
                        actual=act_table.dict_layout_type,
                    )
                )
            if exp_table.dict_source_type != act_table.dict_source_type:
                diffs.append(
                    SchemaDiff(
                        table=table,
                        column=None,
                        diff_type="dict_source_mismatch",
                        expected=exp_table.dict_source_type,
                        actual=act_table.dict_source_type,
                    )
                )
            if (
                exp_table.dict_lifetime_min != act_table.dict_lifetime_min
                or exp_table.dict_lifetime_max != act_table.dict_lifetime_max
            ):
                diffs.append(
                    SchemaDiff(
                        table=table,
                        column=None,
                        diff_type="dict_lifetime_mismatch",
                        expected=f"{exp_table.dict_lifetime_min}/{exp_table.dict_lifetime_max}",
                        actual=f"{act_table.dict_lifetime_min}/{act_table.dict_lifetime_max}",
                    )
                )

        # Column comparison
        exp_cols = {c.name: c for c in exp_table.columns}
        act_cols = {c.name: c for c in act_table.columns}

        for col_name in sorted(set(exp_cols.keys()) - set(act_cols.keys())):
            diffs.append(
                SchemaDiff(
                    table=table,
                    column=col_name,
                    diff_type="missing_column",
                    expected=exp_cols[col_name].type,
                    actual="",
                )
            )

        for col_name in sorted(set(act_cols.keys()) - set(exp_cols.keys())):
            diffs.append(
                SchemaDiff(
                    table=table,
                    column=col_name,
                    diff_type="extra_column",
                    expected="",
                    actual=act_cols[col_name].type,
                )
            )

        for col_name in sorted(set(exp_cols.keys()) & set(act_cols.keys())):
            if exp_cols[col_name].type != act_cols[col_name].type:
                diffs.append(
                    SchemaDiff(
                        table=table,
                        column=col_name,
                        diff_type="type_mismatch",
                        expected=exp_cols[col_name].type,
                        actual=act_cols[col_name].type,
                    )
                )

    return diffs


def detect_drift(cluster: ClickhouseCluster, database: str) -> list[SchemaDiff]:
    """Dump schema from all hosts and compare within each role group.

    Hosts with the same host_cluster_role should have identical schemas,
    but hosts with different roles (e.g. DATA vs COORDINATOR) legitimately differ.
    """
    all_schemas = dump_schema_all_hosts(cluster, database)

    if len(all_schemas) < 2:
        return []

    # Group hosts by role so we only compare like-for-like
    by_role: dict[str | None, list[tuple[HostInfo, dict[str, TableSchema]]]] = {}
    for host, schema in all_schemas.items():
        role = host.host_cluster_role
        by_role.setdefault(role, []).append((host, schema))

    diffs: list[SchemaDiff] = []
    for role, group in by_role.items():
        if len(group) < 2:
            continue
        ref_host, ref_schema = group[0]
        for host, host_schema in group[1:]:
            host_diffs = compare_schemas(ref_schema, host_schema)
            role_label = f" (role={role})" if role else ""
            for diff in host_diffs:
                diff.host = f"{host.connection_info.host} (vs {ref_host.connection_info.host}){role_label}"
            diffs.extend(host_diffs)

    return diffs
