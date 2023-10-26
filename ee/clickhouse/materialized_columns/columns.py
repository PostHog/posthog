import re
from datetime import timedelta
from typing import Dict, List, Literal, Tuple, Union, cast

from clickhouse_driver.errors import ServerException
from django.utils.timezone import now

from posthog.cache_utils import cache_for
from posthog.clickhouse.kafka_engine import trim_quotes_expr
from posthog.client import sync_execute
from posthog.models.instance_setting import get_instance_setting
from posthog.models.property import PropertyName, TableColumn, TableWithProperties
from posthog.models.utils import generate_random_short_suffix
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE, TEST

ColumnName = str
DEFAULT_TABLE_COLUMN: Literal["properties"] = "properties"


TablesWithMaterializedColumns = Union[TableWithProperties, Literal["session_recording_events"]]

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


@cache_for(timedelta(minutes=15))
def get_materialized_columns(
    table: TablesWithMaterializedColumns,
) -> Dict[Tuple[PropertyName, TableColumn], ColumnName]:
    rows = sync_execute(
        """
        SELECT comment, name
        FROM system.columns
        WHERE database = %(database)s
          AND table = %(table)s
          AND comment LIKE '%%column_materializer::%%'
    """,
        {"database": CLICKHOUSE_DATABASE, "table": table},
    )
    if rows and get_instance_setting("MATERIALIZED_COLUMNS_ENABLED"):
        return {_extract_property(comment): column_name for comment, column_name in rows}
    else:
        return {}


def materialize(
    table: TableWithProperties,
    property: PropertyName,
    column_name=None,
    table_column: TableColumn = DEFAULT_TABLE_COLUMN,
    create_minmax_index=not TEST,
) -> None:
    if (property, table_column) in get_materialized_columns(table, use_cache=False):
        if TEST:
            return

        raise ValueError(f"Property already materialized. table={table}, property={property}, column={table_column}")

    if table_column not in SHORT_TABLE_COLUMN_NAME:
        raise ValueError(f"Invalid table_column={table_column} for materialisation")

    column_name = column_name or _materialized_column_name(table, property, table_column)
    # :TRICKY: On cloud, we ON CLUSTER updates to events/sharded_events but not to persons. Why? ¯\_(ツ)_/¯
    execute_on_cluster = f"ON CLUSTER '{CLICKHOUSE_CLUSTER}'" if table == "events" else ""

    if table == "events":
        sync_execute(
            f"""
            ALTER TABLE sharded_{table}
            {execute_on_cluster}
            ADD COLUMN IF NOT EXISTS
            {column_name} VARCHAR MATERIALIZED {TRIM_AND_EXTRACT_PROPERTY.format(table_column=table_column)}
        """,
            {"property": property},
            settings={"alter_sync": 1},
        )
        sync_execute(
            f"""
            ALTER TABLE {table}
            {execute_on_cluster}
            ADD COLUMN IF NOT EXISTS
            {column_name} VARCHAR
        """,
            settings={"alter_sync": 1},
        )
    else:
        sync_execute(
            f"""
            ALTER TABLE {table}
            {execute_on_cluster}
            ADD COLUMN IF NOT EXISTS
            {column_name} VARCHAR MATERIALIZED {TRIM_AND_EXTRACT_PROPERTY.format(table_column=table_column)}
        """,
            {"property": property},
            settings={"alter_sync": 1},
        )

    sync_execute(
        f"ALTER TABLE {table} {execute_on_cluster} COMMENT COLUMN {column_name} %(comment)s",
        {"comment": f"column_materializer::{table_column}::{property}"},
        settings={"alter_sync": 1},
    )

    if create_minmax_index:
        add_minmax_index(table, column_name)


def add_minmax_index(table: TablesWithMaterializedColumns, column_name: str):
    # Note: This will be populated on backfill
    execute_on_cluster = f"ON CLUSTER '{CLICKHOUSE_CLUSTER}'" if table == "events" else ""

    updated_table = "sharded_events" if table == "events" else table
    index_name = f"minmax_{column_name}"

    try:
        sync_execute(
            f"""
            ALTER TABLE {updated_table}
            {execute_on_cluster}
            ADD INDEX {index_name} {column_name}
            TYPE minmax GRANULARITY 1
            """,
            settings={"alter_sync": 1},
        )
    except ServerException as err:
        if "index with this name already exists" not in str(err):
            raise err

    return index_name


def backfill_materialized_columns(
    table: TableWithProperties,
    properties: List[Tuple[PropertyName, TableColumn]],
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
    # :TRICKY: On cloud, we ON CLUSTER updates to events/sharded_events but not to persons. Why? ¯\_(ツ)_/¯
    execute_on_cluster = f"ON CLUSTER '{CLICKHOUSE_CLUSTER}'" if table == "events" else ""

    materialized_columns = get_materialized_columns(table, use_cache=False)

    # Hack from https://github.com/ClickHouse/ClickHouse/issues/19785
    # Note that for this to work all inserts should list columns explicitly
    # Improve this if https://github.com/ClickHouse/ClickHouse/issues/27730 ever gets resolved
    for property, table_column in properties:
        sync_execute(
            f"""
            ALTER TABLE {updated_table}
            {execute_on_cluster}
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
        ALTER TABLE {updated_table}
        {execute_on_cluster}
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
) -> str:
    "Returns a sanitized and unique column name to use for materialized column"

    prefix = "mat_" if table == "events" or table == "groups" else "pmat_"

    if table_column != DEFAULT_TABLE_COLUMN:
        prefix += f"{SHORT_TABLE_COLUMN_NAME[table_column]}_"
    property_str = re.sub("[^0-9a-zA-Z$]", "_", property)

    existing_materialized_columns = set(get_materialized_columns(table, use_cache=False).values())
    suffix = ""

    while f"{prefix}{property_str}{suffix}" in existing_materialized_columns:
        suffix = "_" + generate_random_short_suffix()

    return f"{prefix}{property_str}{suffix}"


def _extract_property(comment: str) -> Tuple[PropertyName, TableColumn]:
    # Old style comments have the format "column_materializer::property", dealing with the default table column.
    # Otherwise, it's "column_materializer::table_column::property"
    split_column = comment.split("::", 2)

    if len(split_column) == 2:
        return split_column[1], DEFAULT_TABLE_COLUMN

    return split_column[2], cast(TableColumn, split_column[1])
