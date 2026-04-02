"""Live schema introspection and drift detection. Shared by both migration approaches."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from posthog.clickhouse.cluster import ClickhouseCluster, HostInfo

if TYPE_CHECKING:
    from posthog.clickhouse.migration_tools.schema_graph import TableEcosystem


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

    return schema


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


def build_ecosystems_from_schema(
    schema: dict[str, TableSchema],
) -> list[TableEcosystem]:
    """Return known ecosystems whose sharded table exists in the schema dump."""
    from posthog.clickhouse.migration_tools.schema_graph import KNOWN_ECOSYSTEMS

    matched: list[TableEcosystem] = []
    for eco in KNOWN_ECOSYSTEMS:
        if eco.sharded_table in schema:
            matched.append(eco)
    return matched


def detect_drift(cluster: ClickhouseCluster, database: str) -> list[SchemaDiff]:
    """Dump schema from all hosts and compare each against the first (reference)."""
    all_schemas = dump_schema_all_hosts(cluster, database)

    if len(all_schemas) < 2:
        return []

    hosts = list(all_schemas.keys())
    reference_host = hosts[0]
    reference_schema = all_schemas[reference_host]

    diffs: list[SchemaDiff] = []
    for host in hosts[1:]:
        host_schema = all_schemas[host]
        host_diffs = compare_schemas(reference_schema, host_schema)
        for diff in host_diffs:
            diff.host = f"{host.connection_info.host} (vs {reference_host.connection_info.host})"
        diffs.extend(host_diffs)

    return diffs
