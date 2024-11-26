from __future__ import annotations

import re
from collections.abc import Iterator
from copy import copy
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Literal, NamedTuple, cast

from django.utils.timezone import now

from posthog.clickhouse.client.connection import default_client
from posthog.clickhouse.cluster import ClickhouseCluster, ConnectionInfo
from posthog.clickhouse.kafka_engine import trim_quotes_expr
from posthog.clickhouse.materialized_columns import ColumnName, TablesWithMaterializedColumns
from posthog.client import sync_execute
from posthog.models.instance_setting import get_instance_setting
from posthog.models.property import PropertyName, TableColumn, TableWithProperties
from posthog.models.utils import generate_random_short_suffix
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE, CLICKHOUSE_PER_TEAM_SETTINGS, TEST

DEFAULT_TABLE_COLUMN: Literal["properties"] = "properties"

TRIM_AND_EXTRACT_PROPERTY = trim_quotes_expr("JSONExtractRaw({table_column}, %(property)s)")

SHORT_TABLE_COLUMN_NAME = {
    "properties": "p",
    "group_properties": "gp",
    "person_properties": "pp",
    "group0_properties": "gp0",
    "group1_properties": "gp1",
    "group2_properties": "gp2",
    "group3_properties": "gp3",
    "group4_properties": "gp4",
}


class MaterializedColumn(NamedTuple):
    name: ColumnName
    details: MaterializedColumnDetails

    @staticmethod
    def get_all(table: TablesWithMaterializedColumns) -> Iterator[MaterializedColumn]:
        rows = sync_execute(
            """
            SELECT name, comment
            FROM system.columns
            WHERE database = %(database)s
                AND table = %(table)s
                AND comment LIKE '%%column_materializer::%%'
                AND comment not LIKE '%%column_materializer::elements_chain::%%'
        """,
            {"database": CLICKHOUSE_DATABASE, "table": table},
        )

        for name, comment in rows:
            yield MaterializedColumn(name, MaterializedColumnDetails.from_column_comment(comment))

    @staticmethod
    def get(table: TablesWithMaterializedColumns, column_name: ColumnName) -> MaterializedColumn:
        # TODO: It would be more efficient to push the filter here down into the `get_all` query, but that would require
        # more a sophisticated method of constructing queries than we have right now, and this data set should be small
        # enough that this doesn't really matter (at least as of writing.)
        columns = [column for column in MaterializedColumn.get_all(table) if column.name == column_name]
        match columns:
            case []:
                raise ValueError("column does not exist")
            case [column]:
                return column
            case _:
                # this should never happen (column names are unique within a table) and suggests an error in the query
                raise ValueError(f"got {len(columns)} columns, expected 0 or 1")


@dataclass(frozen=True)
class MaterializedColumnDetails:
    table_column: TableColumn
    property_name: PropertyName
    is_disabled: bool

    COMMENT_PREFIX = "column_materializer"
    COMMENT_SEPARATOR = "::"
    COMMENT_DISABLED_MARKER = "disabled"

    def as_column_comment(self) -> str:
        bits = [self.COMMENT_PREFIX, self.table_column, self.property_name]
        if self.is_disabled:
            bits.append(self.COMMENT_DISABLED_MARKER)
        return self.COMMENT_SEPARATOR.join(bits)

    @classmethod
    def from_column_comment(cls, comment: str) -> MaterializedColumnDetails:
        match comment.split(cls.COMMENT_SEPARATOR, 3):
            # Old style comments have the format "column_materializer::property", dealing with the default table column.
            case [cls.COMMENT_PREFIX, property_name]:
                return MaterializedColumnDetails(DEFAULT_TABLE_COLUMN, property_name, is_disabled=False)
            # Otherwise, it's "column_materializer::table_column::property" for columns that are active.
            case [cls.COMMENT_PREFIX, table_column, property_name]:
                return MaterializedColumnDetails(cast(TableColumn, table_column), property_name, is_disabled=False)
            # Columns that are marked as disabled have an extra trailer indicating their status.
            case [cls.COMMENT_PREFIX, table_column, property_name, cls.COMMENT_DISABLED_MARKER]:
                return MaterializedColumnDetails(cast(TableColumn, table_column), property_name, is_disabled=True)
            case _:
                raise ValueError(f"unexpected comment format: {comment!r}")


def get_materialized_columns(
    table: TablesWithMaterializedColumns,
    exclude_disabled_columns: bool = False,
) -> dict[tuple[PropertyName, TableColumn], ColumnName]:
    if not get_instance_setting("MATERIALIZED_COLUMNS_ENABLED"):
        return {}

    return {
        (column.details.property_name, column.details.table_column): column.name
        for column in MaterializedColumn.get_all(table)
        if not (exclude_disabled_columns and column.details.is_disabled)
    }


def get_on_cluster_clause_for_table(table: TableWithProperties) -> str:
    return f"ON CLUSTER '{CLICKHOUSE_CLUSTER}'" if table == "events" else ""


def get_cluster() -> ClickhouseCluster:
    extra_hosts = []
    for host_config in map(copy, CLICKHOUSE_PER_TEAM_SETTINGS.values()):
        extra_hosts.append(ConnectionInfo(host_config.pop("host"), host_config.pop("port", None)))
        assert len(host_config) == 0, f"unexpected values: {host_config!r}"
    return ClickhouseCluster(default_client(), extra_hosts=extra_hosts)


class TableInfo(NamedTuple):
    data_table: str
    dist_table: str | None


tables = {
    "events": TableInfo("sharded_events", "events"),
    "person": TableInfo("person", None),
    # TODO ...
}


@dataclass
class CreateColumnOnDataNodesTask:
    table: str
    column: MaterializedColumn
    create_minmax_index: bool

    def execute(self, client):
        client.execute(
            f"""
            ALTER TABLE {self.table}
                ADD COLUMN IF NOT EXISTS {self.column.name} VARCHAR
                    MATERIALIZED {TRIM_AND_EXTRACT_PROPERTY.format(table_column=self.column.details.table_column)},
                COMMENT COLUMN {self.column.name} %(comment)s
            """,
            {
                "comment": self.column.details.as_column_comment(),
                "property": self.column.details.property_name,
            },
            settings={"alter_sync": 2 if TEST else 1},
        )

        if self.create_minmax_index:
            index_name = f"minmax_{self.column.name}"
            client.execute(
                f"""
                ALTER TABLE {self.table}
                ADD INDEX IF NOT EXISTS {index_name} {self.column.name}
                TYPE minmax GRANULARITY 1
                """,
                settings={"alter_sync": 2 if TEST else 1},
            )


@dataclass
class CreateColumnOnQueryNodesTask:
    table: str
    column: MaterializedColumn

    def execute(self, client):
        client.execute(
            f"""
            ALTER TABLE {self.table}
                ADD COLUMN IF NOT EXISTS {self.column.name} VARCHAR,
                COMMENT COLUMN {self.column.name} %(comment)s
            """,
            {"comment": self.column.details.as_column_comment()},
            settings={"alter_sync": 2 if TEST else 1},
        )


def materialize(
    table: TableWithProperties,
    property: PropertyName,
    column_name: ColumnName | None = None,
    table_column: TableColumn = DEFAULT_TABLE_COLUMN,
    create_minmax_index=not TEST,
) -> ColumnName | None:
    if (property, table_column) in get_materialized_columns(table):
        if TEST:
            return None

        raise ValueError(f"Property already materialized. table={table}, property={property}, column={table_column}")

    if table_column not in SHORT_TABLE_COLUMN_NAME:
        raise ValueError(f"Invalid table_column={table_column} for materialisation")

    cluster = get_cluster()
    table_info = tables[table]

    column = MaterializedColumn(
        name=column_name or _materialized_column_name(table, property, table_column),
        details=MaterializedColumnDetails(
            table_column=table_column,
            property_name=property,
            is_disabled=False,
        ),
    )

    create_on_data_nodes = CreateColumnOnDataNodesTask(table_info.data_table, column, create_minmax_index)
    for host, future in cluster.map_shards(create_on_data_nodes.execute).as_completed():
        try:
            future.result()
        except Exception as e:
            raise Exception(f"Failed to run {create_on_data_nodes!r} on {host!r}") from e

    if table_info.dist_table is not None:
        create_on_query_nodes = CreateColumnOnQueryNodesTask(table_info.dist_table, column)
        for host, future in cluster.map_hosts(create_on_query_nodes.execute).as_completed():
            try:
                future.result()
            except Exception as e:
                raise Exception(f"Failed to run {create_on_query_nodes!r} on {host!r}") from e

    return column.name


@dataclass
class UpdateColumnCommentTask:
    table: str
    column: MaterializedColumn

    def execute(self, client):
        client.execute(
            f"ALTER TABLE {self.table} COMMENT COLUMN {self.column.name} %(comment)s",
            {"comment": self.column.details.as_column_comment()},
            settings={"alter_sync": 2 if TEST else 1},
        )


def update_column_is_disabled(table: TablesWithMaterializedColumns, column_name: str, is_disabled: bool) -> None:
    cluster = get_cluster()
    table_info = tables[table]

    task = UpdateColumnCommentTask(
        table,
        MaterializedColumn(
            name=column_name,
            details=replace(
                MaterializedColumn.get(table, column_name).details,
                is_disabled=is_disabled,
            ),
        ),
    )

    method = cluster.map_hosts if table_info.dist_table is not None else cluster.map_shards
    for host, future in method(task.execute).as_completed():
        try:
            future.result()
        except Exception as e:
            raise Exception(f"Failed to run {task!r} on {host!r}") from e


@dataclass
class DropColumnOnDataNodesTask:
    table: str
    column_name: str

    def execute(self, client):
        # XXX: copy/pasted from create task
        index_name = f"minmax_{self.column_name}"
        client.execute(
            f"ALTER TABLE {self.table} DROP INDEX IF EXISTS {index_name}",
            settings={"alter_sync": 2 if TEST else 1},
        )

        client.execute(
            f"ALTER TABLE {self.table} DROP COLUMN IF EXISTS {self.column_name}",
            settings={"alter_sync": 2 if TEST else 1},
        )


@dataclass
class DropColumnOnQueryNodesTask:
    table: str
    column_name: str

    def execute(self, client):
        client.execute(
            f"ALTER TABLE {self.table} DROP COLUMN IF EXISTS {self.column_name}",
            settings={"alter_sync": 2 if TEST else 1},
        )


def drop_column(table: TablesWithMaterializedColumns, column_name: str) -> None:
    cluster = get_cluster()
    table_info = tables[table]

    if table_info.dist_table is not None:
        drop_on_query_nodes = DropColumnOnQueryNodesTask(table_info.dist_table, column_name)
        for host, future in cluster.map_hosts(drop_on_query_nodes.execute).as_completed():
            try:
                future.result()
            except Exception as e:
                raise Exception(f"Failed to run {drop_on_query_nodes!r} on {host!r}") from e

    drop_on_data_nodes = DropColumnOnDataNodesTask(table_info.data_table, column_name)
    for host, future in cluster.map_shards(drop_on_data_nodes.execute).as_completed():
        try:
            future.result()
        except Exception as e:
            raise Exception(f"Failed to run {drop_on_data_nodes!r} on {host!r}") from e


def backfill_materialized_columns(
    table: TableWithProperties,
    properties: list[tuple[PropertyName, TableColumn]],
    backfill_period: timedelta,
    test_settings=None,
) -> None:
    """
    Backfills the materialized column after its creation.

    This will require reading and writing a lot of data on clickhouse disk.
    """

    if len(properties) == 0:
        return

    updated_table = "sharded_events" if table == "events" else table
    on_cluster = get_on_cluster_clause_for_table(table)

    materialized_columns = get_materialized_columns(table)

    # Hack from https://github.com/ClickHouse/ClickHouse/issues/19785
    # Note that for this to work all inserts should list columns explicitly
    # Improve this if https://github.com/ClickHouse/ClickHouse/issues/27730 ever gets resolved
    for property, table_column in properties:
        sync_execute(
            f"""
            ALTER TABLE {updated_table} {on_cluster}
            MODIFY COLUMN
            {materialized_columns[(property, table_column)]} VARCHAR DEFAULT {TRIM_AND_EXTRACT_PROPERTY.format(table_column=table_column)}
            """,
            {"property": property},
            settings=test_settings,
        )

    # Kick off mutations which will update clickhouse partitions in the background. This will return immediately
    assignments = ", ".join(
        f"{materialized_columns[property_and_column]} = {materialized_columns[property_and_column]}"
        for property_and_column in properties
    )

    sync_execute(
        f"""
        ALTER TABLE {updated_table} {on_cluster}
        UPDATE {assignments}
        WHERE {"timestamp > %(cutoff)s" if table == "events" else "1 = 1"}
        """,
        {"cutoff": (now() - backfill_period).strftime("%Y-%m-%d")},
        settings=test_settings,
    )


def _materialized_column_name(
    table: TableWithProperties,
    property: PropertyName,
    table_column: TableColumn = DEFAULT_TABLE_COLUMN,
) -> ColumnName:
    "Returns a sanitized and unique column name to use for materialized column"

    prefix = "pmat_" if table == "person" else "mat_"

    if table_column != DEFAULT_TABLE_COLUMN:
        prefix += f"{SHORT_TABLE_COLUMN_NAME[table_column]}_"
    property_str = re.sub("[^0-9a-zA-Z$]", "_", property)

    existing_materialized_columns = set(get_materialized_columns(table).values())
    suffix = ""

    while f"{prefix}{property_str}{suffix}" in existing_materialized_columns:
        suffix = "_" + generate_random_short_suffix()

    return f"{prefix}{property_str}{suffix}"
