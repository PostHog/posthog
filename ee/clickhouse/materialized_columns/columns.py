import re
from datetime import timedelta
from typing import Dict, List, Literal, Union

from constance import config
from django.utils.timezone import now

from ee.clickhouse.materialized_columns.util import cache_for
from ee.clickhouse.replication.utils import clickhouse_is_replicated
from ee.clickhouse.sql.clickhouse import trim_quotes_expr
from posthog.client import sync_execute
from posthog.models.property import PropertyName, TableWithProperties
from posthog.models.utils import generate_random_short_suffix
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE, TEST

ColumnName = str

TablesWithMaterializedColumns = Union[TableWithProperties, Literal["session_recording_events"]]

TRIM_AND_EXTRACT_PROPERTY = trim_quotes_expr("JSONExtractRaw(properties, %(property)s)")


@cache_for(timedelta(minutes=15))
def get_materialized_columns(table: TablesWithMaterializedColumns) -> Dict[PropertyName, ColumnName]:
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
    if rows and getattr(config, "MATERIALIZED_COLUMNS_ENABLED"):
        return {extract_property(comment): column_name for comment, column_name in rows}
    else:
        return {}


def materialize(table: TableWithProperties, property: PropertyName, column_name=None) -> None:
    if property in get_materialized_columns(table, use_cache=False):
        if TEST:
            return

        raise ValueError(f"Property already materialized. table={table}, property={property}")

    column_name = column_name or materialized_column_name(table, property)
    # :TRICKY: On cloud, we ON CLUSTER updates to events/sharded_events but not to persons. Why? ¯\_(ツ)_/¯
    execute_on_cluster = f"ON CLUSTER '{CLICKHOUSE_CLUSTER}'" if table == "events" else ""

    if clickhouse_is_replicated() and table == "events":
        sync_execute(
            f"""
            ALTER TABLE sharded_{table}
            {execute_on_cluster}
            ADD COLUMN IF NOT EXISTS
            {column_name} VARCHAR MATERIALIZED {TRIM_AND_EXTRACT_PROPERTY}
        """,
            {"property": property},
        )
        sync_execute(
            f"""
            ALTER TABLE {table}
            {execute_on_cluster}
            ADD COLUMN IF NOT EXISTS
            {column_name} VARCHAR
        """
        )
    else:
        sync_execute(
            f"""
            ALTER TABLE {table}
            {execute_on_cluster}
            ADD COLUMN IF NOT EXISTS
            {column_name} VARCHAR MATERIALIZED {TRIM_AND_EXTRACT_PROPERTY}
        """,
            {"property": property},
        )

    sync_execute(
        f"ALTER TABLE {table} {execute_on_cluster} COMMENT COLUMN {column_name} %(comment)s",
        {"comment": f"column_materializer::{property}"},
    )


def backfill_materialized_columns(
    table: TableWithProperties, properties: List[PropertyName], backfill_period: timedelta, test_settings=None
) -> None:
    """
    Backfills the materialized column after its creation.

    This will require reading and writing a lot of data on clickhouse disk.
    """

    if len(properties) == 0:
        return

    updated_table = "sharded_events" if clickhouse_is_replicated() and table == "events" else table
    # :TRICKY: On cloud, we ON CLUSTER updates to events/sharded_events but not to persons. Why? ¯\_(ツ)_/¯
    execute_on_cluster = f"ON CLUSTER '{CLICKHOUSE_CLUSTER}'" if table == "events" else ""

    materialized_columns = get_materialized_columns(table, use_cache=False)

    # Hack from https://github.com/ClickHouse/ClickHouse/issues/19785
    # Note that for this to work all inserts should list columns explicitly
    # Improve this if https://github.com/ClickHouse/ClickHouse/issues/27730 ever gets resolved
    for property in properties:
        sync_execute(
            f"""
            ALTER TABLE {updated_table}
            {execute_on_cluster}
            MODIFY COLUMN
            {materialized_columns[property]} VARCHAR DEFAULT {TRIM_AND_EXTRACT_PROPERTY}
            """,
            {"property": property},
            settings=test_settings,
        )

    # Kick off mutations which will update clickhouse partitions in the background. This will return immediately
    assignments = ", ".join(
        f"{materialized_columns[property]} = {materialized_columns[property]}" for property in properties
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


def materialized_column_name(table: TableWithProperties, property: PropertyName) -> str:
    "Returns a sanitized and unique column name to use for materialized column"

    prefix = "mat_" if table == "events" else "pmat_"
    property_str = re.sub("[^0-9a-zA-Z$]", "_", property)

    existing_materialized_columns = set(get_materialized_columns(table, use_cache=False).values())
    suffix = ""

    while f"{prefix}{property_str}{suffix}" in existing_materialized_columns:
        suffix = "_" + generate_random_short_suffix()

    return f"{prefix}{property_str}{suffix}"


def extract_property(comment: str) -> PropertyName:
    return comment.split("::", 1)[1]
