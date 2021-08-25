import random
import re
import string
from datetime import timedelta
from typing import Dict

from ee.clickhouse.client import sync_execute
from ee.clickhouse.materialized_columns.util import cache_for
from posthog.models.property import PropertyName, TableWithProperties
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

ColumnName = str


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


def materialize(table: TableWithProperties, property: PropertyName, distributed: bool = False) -> None:
    column_name = materialized_column_name(table, property)
    if distributed:
        sync_execute(
            f"""
            ALTER TABLE sharded_{table}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            ADD COLUMN IF NOT EXISTS
            {column_name} VARCHAR MATERIALIZED trim(BOTH '"' FROM JSONExtractRaw(properties, %(property)s))
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
            {column_name} VARCHAR MATERIALIZED trim(BOTH '"' FROM JSONExtractRaw(properties, %(property)s))
        """,
            {"property": property},
        )

    sync_execute(
        f"ALTER TABLE {table} ON CLUSTER {CLICKHOUSE_CLUSTER} COMMENT COLUMN {column_name} %(comment)s",
        {"comment": f"column_materializer::{property}"},
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
