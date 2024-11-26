from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from copy import copy
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, Literal, NamedTuple, TypeVar, cast

from clickhouse_driver import Client
from django.utils.timezone import now

from posthog.clickhouse.client.connection import default_client
from posthog.clickhouse.cluster import ClickhouseCluster, ConnectionInfo, FuturesMap, HostInfo
from posthog.clickhouse.kafka_engine import trim_quotes_expr
from posthog.clickhouse.materialized_columns import ColumnName, TablesWithMaterializedColumns
from posthog.client import sync_execute
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.instance_setting import get_instance_setting
from posthog.models.person.sql import PERSONS_TABLE
from posthog.models.property import PropertyName, TableColumn, TableWithProperties
from posthog.models.utils import generate_random_short_suffix
from posthog.settings import CLICKHOUSE_DATABASE, CLICKHOUSE_PER_TEAM_SETTINGS, TEST

T = TypeVar("T")

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


def get_cluster() -> ClickhouseCluster:
    extra_hosts = []
    for host_config in map(copy, CLICKHOUSE_PER_TEAM_SETTINGS.values()):
        extra_hosts.append(ConnectionInfo(host_config.pop("host"), host_config.pop("port", None)))
        assert len(host_config) == 0, f"unexpected values: {host_config!r}"
    return ClickhouseCluster(default_client(), extra_hosts=extra_hosts)


@dataclass
class TableInfo:
    data_table: str

    @property
    def read_table(self) -> str:
        return self.data_table

    def map_data_nodes(self, cluster: ClickhouseCluster, fn: Callable[[Client], T]) -> FuturesMap[HostInfo, T]:
        return cluster.map_all_hosts(fn)


@dataclass
class ShardedTableInfo(TableInfo):
    dist_table: str

    @property
    def read_table(self) -> str:
        return self.dist_table

    def map_data_nodes(self, cluster: ClickhouseCluster, fn: Callable[[Client], T]) -> FuturesMap[HostInfo, T]:
        return cluster.map_one_host_per_shard(fn)


tables: dict[str, TableInfo | ShardedTableInfo] = {
    PERSONS_TABLE: TableInfo(PERSONS_TABLE),
    "events": ShardedTableInfo(EVENTS_DATA_TABLE, "events"),
}


@dataclass
class CreateColumnOnDataNodesTask:
    table: str
    column: MaterializedColumn
    create_minmax_index: bool
    add_column_comment: bool

    def execute(self, client: Client) -> None:
        actions = [
            f"""
            ADD COLUMN IF NOT EXISTS {self.column.name} VARCHAR
                MATERIALIZED {TRIM_AND_EXTRACT_PROPERTY.format(table_column=self.column.details.table_column)}
            """,
        ]
        parameters = {"property": self.column.details.property_name}

        if self.add_column_comment:
            actions.append(f"COMMENT COLUMN {self.column.name} %(comment)s")
            parameters["comment"] = self.column.details.as_column_comment()

        if self.create_minmax_index:
            index_name = f"minmax_{self.column.name}"
            actions.append(f"ADD INDEX IF NOT EXISTS {index_name} {self.column.name} TYPE minmax GRANULARITY 1")

        client.execute(
            f"ALTER TABLE {self.table} " + ", ".join(actions),
            parameters,
            settings={"alter_sync": 2 if TEST else 1},
        )


@dataclass
class CreateColumnOnQueryNodesTask:
    table: str
    column: MaterializedColumn

    def execute(self, client: Client) -> None:
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

    table_info.map_data_nodes(
        cluster,
        CreateColumnOnDataNodesTask(
            table_info.data_table,
            column,
            create_minmax_index,
            add_column_comment=table_info.read_table == table_info.data_table,
        ).execute,
    ).result()

    if isinstance(table_info, ShardedTableInfo):
        cluster.map_all_hosts(
            CreateColumnOnQueryNodesTask(
                table_info.dist_table,
                column,
            ).execute
        ).result()

    return column.name


@dataclass
class UpdateColumnCommentTask:
    table: str
    column: MaterializedColumn

    def execute(self, client: Client) -> None:
        client.execute(
            f"ALTER TABLE {self.table} COMMENT COLUMN {self.column.name} %(comment)s",
            {"comment": self.column.details.as_column_comment()},
            settings={"alter_sync": 2 if TEST else 1},
        )


def update_column_is_disabled(table: TablesWithMaterializedColumns, column_name: str, is_disabled: bool) -> None:
    cluster = get_cluster()
    table_info = tables[table]

    cluster.map_all_hosts(
        UpdateColumnCommentTask(
            table_info.read_table,
            MaterializedColumn(
                name=column_name,
                details=replace(
                    MaterializedColumn.get(table, column_name).details,
                    is_disabled=is_disabled,
                ),
            ),
        ).execute
    ).result()


@dataclass
class DropColumnTask:
    table: str
    column_name: str
    try_drop_index: bool

    def execute(self, client: Client) -> None:
        # XXX: copy/pasted from create task
        if self.try_drop_index:
            index_name = f"minmax_{self.column_name}"
            client.execute(
                f"ALTER TABLE {self.table} DROP INDEX IF EXISTS {index_name}",
                settings={"alter_sync": 2 if TEST else 1},
            )

        client.execute(
            f"ALTER TABLE {self.table} DROP COLUMN IF EXISTS {self.column_name}",
            settings={"alter_sync": 2 if TEST else 1},
        )


def drop_column(table: TablesWithMaterializedColumns, column_name: str) -> None:
    cluster = get_cluster()
    table_info = tables[table]

    if isinstance(table_info, ShardedTableInfo):
        cluster.map_all_hosts(
            DropColumnTask(
                table_info.dist_table,
                column_name,
                try_drop_index=False,  # no indexes on distributed tables
            ).execute
        ).result()

    table_info.map_data_nodes(
        cluster,
        DropColumnTask(
            table_info.data_table,
            column_name,
            try_drop_index=True,
        ).execute,
    ).result()


@dataclass
class BackfillColumnTask:
    table: str
    columns: list[MaterializedColumn]
    backfill_period: timedelta | None
    test_settings: dict[str, Any] | None

    def execute(self, client: Client) -> None:
        # Hack from https://github.com/ClickHouse/ClickHouse/issues/19785
        # Note that for this to work all inserts should list columns explicitly
        # Improve this if https://github.com/ClickHouse/ClickHouse/issues/27730 ever gets resolved
        for column in self.columns:
            client.execute(
                f"""
                ALTER TABLE {self.table}
                MODIFY COLUMN {column.name} VARCHAR DEFAULT {TRIM_AND_EXTRACT_PROPERTY.format(table_column=column.details.table_column)}
                """,
                {"property": column.details.property_name},
                settings=self.test_settings,
            )

        # Kick off mutations which will update clickhouse partitions in the background. This will return immediately
        assignments = ", ".join(f"{column.name} = {column.name}" for column in self.columns)

        if self.backfill_period is not None:
            where_clause = "timestamp > %(cutoff)s"
            parameters = {"cutoff": (now() - self.backfill_period).strftime("%Y-%m-%d")}
        else:
            where_clause = "1 = 1"
            parameters = {}

        client.execute(
            f"ALTER TABLE {self.table} UPDATE {assignments} WHERE {where_clause}",
            parameters,
            settings=self.test_settings,
        )


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

    cluster = get_cluster()
    table_info = tables[table]

    # TODO: this will eventually need to handle duplicates
    materialized_columns = {
        (column.details.property_name, column.details.table_column): column
        for column in MaterializedColumn.get_all(table)
    }
    columns = [materialized_columns[property] for property in properties]

    table_info.map_data_nodes(
        cluster,
        BackfillColumnTask(
            table_info.data_table,
            columns,
            backfill_period if table == "events" else None,  # XXX
            test_settings,
        ).execute,
    ).result()


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
