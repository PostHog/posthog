from __future__ import annotations

import re
import random
import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, Literal, TypeVar, cast

from django.core.cache import cache
from django.utils.timezone import now

from clickhouse_driver import Client

from posthog.cache_utils import cache_for
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.cluster import ClickhouseCluster, FuturesMap, HostInfo, get_cluster
from posthog.clickhouse.kafka_engine import trim_quotes_expr
from posthog.clickhouse.materialized_columns import (
    MATERIALIZATION_VALID_TABLES,
    ColumnName,
    TablesWithMaterializedColumns,
)
from posthog.clickhouse.query_tagging import tags_context
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.person.sql import PERSONS_TABLE
from posthog.models.property import PropertyName, TableColumn, TableWithProperties
from posthog.models.utils import generate_random_short_suffix
from posthog.settings import (
    CLICKHOUSE_DATABASE,
    MATERIALIZED_COLUMNS_CACHE_TIMEOUT,
    MATERIALIZED_COLUMNS_USE_CACHE,
    TEST,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_TABLE_COLUMN: Literal["properties"] = "properties"

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


def _clear_materialized_columns_cache(table: TablesWithMaterializedColumns) -> None:
    """Clear the cache for materialized columns after mutations."""
    cache_key = get_materialized_columns_cache_key(table)
    cache.delete(cache_key)


def get_materialized_columns_cache_key(table: TablesWithMaterializedColumns) -> str:
    return f"materialized_columns:v2:{table}"


@dataclass
class MaterializedColumn:
    name: ColumnName
    details: MaterializedColumnDetails
    is_nullable: bool
    has_minmax_index: bool = False
    has_bloom_filter_index: bool = False
    has_ngram_lower_index: bool = False

    @property
    def type(self) -> str:
        if self.is_nullable:
            return "Nullable(String)"
        else:
            return "String"

    def get_expression_and_parameters(self) -> tuple[str, dict[str, Any]]:
        if self.is_nullable:
            return (
                f"JSONExtract({self.details.table_column}, %(property_name)s, %(property_type)s)",
                {"property_name": self.details.property_name, "property_type": self.type},
            )
        else:
            return (
                trim_quotes_expr(f"JSONExtractRaw({self.details.table_column}, %(property)s)"),
                {"property": self.details.property_name},
            )

    @staticmethod
    def _get_all(table: TablesWithMaterializedColumns) -> list[tuple[str, str, bool, list[str]]]:
        refresh_cache = random.random() < 0.002  # we run around 50 of those queries per minute
        if table in MATERIALIZATION_VALID_TABLES and not refresh_cache and MATERIALIZED_COLUMNS_USE_CACHE:
            cache_key = get_materialized_columns_cache_key(table)

            try:
                cached_result = cache.get(cache_key)
                if cached_result is not None:
                    return cached_result
            except Exception:
                # If cache fails, continue to query ClickHouse
                pass

        # Get the data table name for index lookups (indexes are on data table, not distributed table)
        table_info = tables.get(table)
        data_table = table_info.data_table if table_info else table

        with tags_context(name="get_all_materialized_columns"):
            # Query columns and their indexes using multiple LEFT JOINs
            # Returns index names as an array, parsed in Python to set boolean flags
            # Note: Columns exist on both distributed and data tables, but indexes only exist on data tables
            result = sync_execute(
                """
                SELECT
                    c.name,
                    c.comment,
                    c.type like 'Nullable(%%)' as is_nullable,
                    arrayFilter(x -> x != '', [i_minmax.name, i_bf.name, i_ngram.name]) as index_names
                FROM system.columns c
                LEFT JOIN system.data_skipping_indices i_minmax
                    ON i_minmax.database = c.database
                    AND i_minmax.table = %(data_table)s
                    AND i_minmax.name = concat('minmax_', c.name)
                LEFT JOIN system.data_skipping_indices i_bf
                    ON i_bf.database = c.database
                    AND i_bf.table = %(data_table)s
                    AND i_bf.name = concat('bloom_filter_', c.name)
                LEFT JOIN system.data_skipping_indices i_ngram
                    ON i_ngram.database = c.database
                    AND i_ngram.table = %(data_table)s
                    AND i_ngram.name = concat('ngram_bf_lower_', c.name)
                WHERE c.database = %(database)s
                  AND c.table = %(table)s
                  AND c.comment LIKE '%%column_materializer::%%'
                  AND c.comment not LIKE '%%column_materializer::elements_chain::%%'
                """,
                {"database": CLICKHOUSE_DATABASE, "table": table, "data_table": data_table},
                ch_user=ClickHouseUser.HOGQL,
            )

        if table in MATERIALIZATION_VALID_TABLES and MATERIALIZED_COLUMNS_USE_CACHE:
            try:
                cache.set(cache_key, result, MATERIALIZED_COLUMNS_CACHE_TIMEOUT)
            except Exception:
                # If cache set fails, log but don't fail the request
                logger.warning("Failed to cache materialized columns for table %s", table)

        return result

    @staticmethod
    def get_all(table: TablesWithMaterializedColumns) -> Iterator[MaterializedColumn]:
        if table not in MATERIALIZATION_VALID_TABLES:
            logger.error("HogQL trying to get materialized columns for table: %s", table)
            return

        rows = MaterializedColumn._get_all(table)
        for name, comment, is_nullable, index_names in rows:
            has_minmax = any(idx and idx.startswith("minmax_") for idx in index_names)
            has_bloom = any(idx and idx.startswith("bloom_filter_") for idx in index_names)
            has_ngram = any(idx and idx.startswith("ngram_bf_lower_") for idx in index_names)
            yield MaterializedColumn(
                name,
                MaterializedColumnDetails.from_column_comment(comment),
                is_nullable=bool(is_nullable),
                has_minmax_index=has_minmax,
                has_bloom_filter_index=has_bloom,
                has_ngram_lower_index=has_ngram,
            )

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


@cache_for(timedelta(minutes=15), background_refresh=True)
def get_materialized_columns(
    table: TablesWithMaterializedColumns,
) -> dict[tuple[PropertyName, TableColumn], MaterializedColumn]:
    return {
        (column.details.property_name, column.details.table_column): column
        for column in MaterializedColumn.get_all(table)
    }


@cache_for(timedelta(minutes=15), background_refresh=True)
def get_enabled_materialized_columns(
    table: TablesWithMaterializedColumns,
) -> dict[tuple[PropertyName, TableColumn], MaterializedColumn]:
    return {k: column for k, column in get_materialized_columns(table).items() if not column.details.is_disabled}


@dataclass
class TableInfo:
    data_table: str

    @property
    def read_table(self) -> str:
        return self.data_table

    def map_data_nodes(self, cluster: ClickhouseCluster, fn: Callable[[Client], T]) -> FuturesMap[HostInfo, T]:
        first_shard = next(iter(cluster.shards))
        return cluster.map_any_host_in_shards({first_shard: fn})


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
    "events": ShardedTableInfo(EVENTS_DATA_TABLE(), "events"),
}


def get_minmax_index_name(column: str) -> str:
    return f"minmax_{column}"


def get_bloom_filter_index_name(column: str) -> str:
    return f"bloom_filter_{column}"


def get_ngram_lower_index_name(column: str) -> str:
    return f"ngram_bf_lower_{column}"


@dataclass
class CreateColumnOnDataNodesTask:
    table: str
    column: MaterializedColumn
    create_minmax_index: bool
    add_column_comment: bool
    create_bloom_filter_index: bool = False
    create_ngram_lower_index: bool = False

    def execute(self, client: Client) -> None:
        expression, parameters = self.column.get_expression_and_parameters()
        actions = [
            f"ADD COLUMN IF NOT EXISTS {self.column.name} {self.column.type} DEFAULT {expression}",
        ]

        if self.add_column_comment:
            actions.append(f"COMMENT COLUMN {self.column.name} %(comment)s")
            parameters["comment"] = self.column.details.as_column_comment()

        if self.create_minmax_index:
            index_name = get_minmax_index_name(self.column.name)
            actions.append(f"ADD INDEX IF NOT EXISTS {index_name} {self.column.name} TYPE minmax GRANULARITY 1")

        if self.create_bloom_filter_index:
            index_name = get_bloom_filter_index_name(self.column.name)
            actions.append(
                f"ADD INDEX IF NOT EXISTS {index_name} {self.column.name} TYPE bloom_filter(0.01) GRANULARITY 1"
            )

        if self.create_ngram_lower_index:
            # There are 2 limitations in clickhouse we need to work around
            # * clickhouse does not support a case-insensitive ngram index, so we need to call lower() on both sides and index lower(col)
            # * clickhouse does not support ngram indexes on nullable columns, so we need to wrap the nullable version in coalesce(col, '')
            # If either of these 2 limitations change, we should simplify this
            index_name = get_ngram_lower_index_name(self.column.name)
            if self.column.is_nullable:
                actions.append(
                    f"ADD INDEX IF NOT EXISTS {index_name} lower(coalesce({self.column.name}, '')) TYPE ngrambf_v1(3, 256, 2, 0) GRANULARITY 1"
                )
            else:
                actions.append(
                    f"ADD INDEX IF NOT EXISTS {index_name} lower({self.column.name}) TYPE ngrambf_v1(3, 256, 2, 0) GRANULARITY 1"
                )

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
                ADD COLUMN IF NOT EXISTS {self.column.name} {self.column.type},
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
    is_nullable: bool = False,
    create_bloom_filter_index: bool = False,
    create_ngram_lower_index: bool = False,
) -> MaterializedColumn:
    if existing_column := get_materialized_columns(table).get((property, table_column)):
        if TEST:
            return existing_column

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
        is_nullable=is_nullable,
    )

    table_info.map_data_nodes(
        cluster,
        CreateColumnOnDataNodesTask(
            table_info.data_table,
            column,
            create_minmax_index,
            add_column_comment=table_info.read_table == table_info.data_table,
            create_bloom_filter_index=create_bloom_filter_index,
            create_ngram_lower_index=create_ngram_lower_index,
        ).execute,
    ).result()

    if isinstance(table_info, ShardedTableInfo):
        cluster.map_all_hosts(
            CreateColumnOnQueryNodesTask(
                table_info.dist_table,
                column,
            ).execute
        ).result()

    _clear_materialized_columns_cache(table)
    return column


@dataclass
class UpdateColumnCommentTask:
    table: str
    columns: list[MaterializedColumn]

    def execute(self, client: Client) -> None:
        actions = []
        parameters = {}
        for i, column in enumerate(self.columns):
            parameter_name = f"comment_{i}"
            actions.append(f"COMMENT COLUMN {column.name} %({parameter_name})s")
            parameters[parameter_name] = column.details.as_column_comment()

        client.execute(
            f"ALTER TABLE {self.table} " + ", ".join(actions),
            parameters,
            settings={"alter_sync": 2 if TEST else 1},
        )


def update_column_is_disabled(
    table: TablesWithMaterializedColumns, column_names: Iterable[str], is_disabled: bool
) -> None:
    cluster = get_cluster()
    table_info = tables[table]

    columns = [MaterializedColumn.get(table, column_name) for column_name in column_names]

    cluster.map_all_hosts(
        UpdateColumnCommentTask(
            table_info.read_table,
            [replace(column, details=replace(column.details, is_disabled=is_disabled)) for column in columns],
        ).execute
    ).result()

    _clear_materialized_columns_cache(table)


def check_index_exists(client: Client, table: str, index: str) -> bool:
    [(count,)] = client.execute(
        """
        SELECT count()
        FROM system.data_skipping_indices
        WHERE database = currentDatabase()
          AND table = %(table)s
          AND name = %(name)s
        """,
        {"table": table, "name": index},
    )
    assert 1 >= count >= 0
    return bool(count)


def check_column_exists(client: Client, table: str, column: str) -> bool:
    [(count,)] = client.execute(
        """
        SELECT count()
        FROM system.columns
        WHERE database = currentDatabase()
          AND table = %(table)s
          AND name = %(name)s
        """,
        {"table": table, "name": column},
    )
    assert 1 >= count >= 0
    return bool(count)


@dataclass
class DropColumnTask:
    table: str
    column_names: list[str]
    try_drop_index: bool

    def execute(self, client: Client) -> None:
        actions = []

        for column_name in self.column_names:
            if self.try_drop_index:
                for get_index_name_fn in [
                    get_minmax_index_name,
                    get_bloom_filter_index_name,
                    get_ngram_lower_index_name,
                ]:
                    index_name = get_index_name_fn(column_name)
                    drop_index_action = f"DROP INDEX IF EXISTS {index_name}"
                    if check_index_exists(client, self.table, index_name):
                        actions.append(drop_index_action)
                    else:
                        logger.info("Skipping %r, nothing to do...", drop_index_action)

            drop_column_action = f"DROP COLUMN IF EXISTS {column_name}"
            if check_column_exists(client, self.table, column_name):
                actions.append(drop_column_action)
            else:
                logger.info("Skipping %r, nothing to do...", drop_column_action)

        if actions:
            client.execute(
                f"ALTER TABLE {self.table} " + ", ".join(actions),
                settings={"alter_sync": 2 if TEST else 1},
            )


def drop_column(table: TablesWithMaterializedColumns, column_names: Iterable[str]) -> None:
    cluster = get_cluster()
    table_info = tables[table]
    column_names = [*column_names]

    if isinstance(table_info, ShardedTableInfo):
        cluster.map_all_hosts(
            DropColumnTask(
                table_info.dist_table,
                column_names,
                try_drop_index=False,  # no indexes on distributed tables
            ).execute
        ).result()

    table_info.map_data_nodes(
        cluster,
        DropColumnTask(
            table_info.data_table,
            column_names,
            try_drop_index=True,
        ).execute,
    ).result()

    _clear_materialized_columns_cache(table)


@dataclass
class BackfillColumnTask:
    table: str
    columns: list[MaterializedColumn]
    backfill_period: timedelta | None
    test_settings: dict[str, Any] | None

    def execute(self, client: Client) -> None:
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
    columns: Iterable[MaterializedColumn],
    backfill_period: timedelta,
    test_settings=None,
) -> None:
    """
    Backfills the materialized column after its creation.

    This will require reading and writing a lot of data on clickhouse disk.
    """
    cluster = get_cluster()
    table_info = tables[table]

    table_info.map_data_nodes(
        cluster,
        BackfillColumnTask(
            table_info.data_table,
            [*columns],
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

    existing_materialized_column_names = {column.name for column in get_materialized_columns(table).values()}
    suffix = ""

    while f"{prefix}{property_str}{suffix}" in existing_materialized_column_names:
        suffix = "_" + generate_random_short_suffix()

    return f"{prefix}{property_str}{suffix}"
