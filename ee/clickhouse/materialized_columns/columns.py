import random
import re
import string
from datetime import timedelta
from typing import Dict, List, Optional

from django.utils.timezone import now

from ee.clickhouse.client import sync_execute
from ee.clickhouse.materialized_columns.util import cache_for
from posthog.models.property import PropertyName, TableWithProperties
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE, CLICKHOUSE_REPLICATION

ColumnName = str

TRIM_AND_EXTRACT_PROPERTY = "trim(BOTH '\"' FROM JSONExtractRaw(properties, %(property)s))"


@cache_for(timedelta(minutes=15))
def get_materialized_columns(table: TableWithProperties) -> Dict[PropertyName, ColumnName]:
    rows = sync_execute(
        """
        SELECT comment, name
        FROM system.columns
        WHERE database = %(database)s
          AND table = %(table)s
          AND default_kind = 'MATERIALIZED'
          AND comment LIKE '%%column_materializer::%%'
    """,
        {"database": CLICKHOUSE_DATABASE, "table": table},
    )
    if rows:
        return {extract_property(comment): column_name for comment, column_name in rows}
    else:
        return {}


def materialize(table: TableWithProperties, property: PropertyName) -> None:
    column_name = materialized_column_name(table, property)
    if CLICKHOUSE_REPLICATION and table == "events":
        sync_execute(
            f"""
            ALTER TABLE sharded_{table}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            ADD COLUMN IF NOT EXISTS
            {column_name} VARCHAR MATERIALIZED {TRIM_AND_EXTRACT_PROPERTY}
        """,
            {"property": property},
        )
        sync_execute(
            f"""
            ALTER TABLE {table}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            ADD COLUMN IF NOT EXISTS
            {column_name} VARCHAR
        """
        )
    else:
        sync_execute(
            f"""
            ALTER TABLE {table}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            ADD COLUMN IF NOT EXISTS
            {column_name} VARCHAR MATERIALIZED {TRIM_AND_EXTRACT_PROPERTY}
        """,
            {"property": property},
        )

    sync_execute(
        f"ALTER TABLE {table} ON CLUSTER {CLICKHOUSE_CLUSTER} COMMENT COLUMN {column_name} %(comment)s",
        {"comment": f"column_materializer::{property}"},
    )


def backfill_materialized_events_column(properties: List[PropertyName], backfill_period: timedelta) -> None:
    """
    Backfills the materialized column after its creation.

    This will require reading and writing a lot of data on clickhouse disk, hack from

    """
    table = "sharded_events" if CLICKHOUSE_REPLICATION else "events"

    materialized_columns = get_materialized_columns("events")

    # Hack from https://github.com/ClickHouse/ClickHouse/issues/19785
    # Note that for this to work all inserts should list columns explicitly
    # Improve this if https://github.com/ClickHouse/ClickHouse/issues/27730 ever gets resolved
    for property in properties:
        sync_execute(
            f"""
            ALTER TABLE {table}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            MODIFY COLUMN
            {materialized_columns[property]} VARCHAR DEFAULT {TRIM_AND_EXTRACT_PROPERTY}
            """,
            {"property": property},
        )

    # Kick off mutations which will update clickhouse partitions in the background. This will return immediately
    assignments = ", ".join(
        f"{materialized_columns[property]} = {materialized_columns[property]}" for property in properties
    )
    cutoff = (now() - backfill_period).strftime("%Y-%m-%d")
    sync_execute(
        f"""
        ALTER TABLE {table}
        ON CLUSTER {CLICKHOUSE_CLUSTER}
        UPDATE {assignments}
        WHERE timestamp > {cutoff}
        """
    )

    # Update the schema back even though updates are ongoing - no validations against this at least.
    for property in properties:
        sync_execute(
            f"""
            ALTER TABLE {table}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            MODIFY COLUMN
            {materialized_columns[property]} VARCHAR MATERIALIZED {TRIM_AND_EXTRACT_PROPERTY}
            """,
            {"property": property},
        )


def materialized_column_name(table: TableWithProperties, property: PropertyName) -> str:
    "Returns a sanitized and unique column name to use for materialized column"

    prefix = "mat_" if table == "events" else "pmat_"
    property_str = re.sub("[^0-9a-zA-Z$]", "_", property)

    existing_materialized_columns = set(get_materialized_columns(table, use_cache=False).values())
    suffix = ""

    while f"{prefix}{property_str}{suffix}" in existing_materialized_columns:
        suffix = "_" + "".join(random.choice(string.ascii_letters) for _ in range(4))

    return f"{prefix}{property_str}{suffix}"


def extract_property(comment: str) -> PropertyName:
    return comment.split("::", 1)[1]
