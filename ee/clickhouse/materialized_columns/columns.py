import re
from datetime import timedelta
from functools import wraps
from typing import Dict, Literal, no_type_check

from django.utils.timezone import now

from ee.clickhouse.client import sync_execute
from posthog.models.property import PropertyName
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE, TEST

ColumnName = str
TableWithProperties = Literal["events", "person"]


def cache_for(cache_time: timedelta):
    def wrapper(fn):
        @wraps(fn)
        @no_type_check
        def memoized_fn(*args, use_cache=not TEST):
            current_time = now()
            if (
                args not in memoized_fn.__cache
                or current_time - memoized_fn.__cache[args][0] > cache_time
                or not use_cache
            ):
                memoized_fn.__cache[args] = (current_time, fn(*args))
            return memoized_fn.__cache[args][1]

        memoized_fn.__cache = {}
        return memoized_fn

    return wrapper


@cache_for(timedelta(minutes=15))
def get_materialized_columns(table: str) -> Dict[PropertyName, ColumnName]:
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


def materialize(table: str, property: str, distributed: bool = False) -> None:
    column_name = f"mat_{re.sub('[^0-9a-zA-Z]+', '_', property)}"
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


def extract_property(comment: str) -> PropertyName:
    return comment.split("::", 1)[1]
