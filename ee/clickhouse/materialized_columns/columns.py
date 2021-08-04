from collections import defaultdict
from functools import wraps
from typing import Dict, no_type_check

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now

from ee.clickhouse.client import sync_execute
from posthog.settings import CLICKHOUSE_DATABASE

Property = str
ColumnName = str


def cache_for(cache_time: relativedelta):
    def wrapper(fn):
        @wraps(fn)
        @no_type_check
        def memoized_fn(*args):
            current_time = now()
            if args not in memoized_fn.__cache or current_time - memoized_fn.__cache[args][0] > cache_time:
                memoized_fn.__cache[args] = (current_time, fn(*args))
            return memoized_fn.__cache[args][1]

        memoized_fn.__cache = {}
        return memoized_fn

    return wrapper


@cache_for(relativedelta(minutes=15))
def get_materialized_columns(table: str) -> Dict[Property, ColumnName]:
    rows = sync_execute(
        """
        SELECT comment, name
        FROM system.columns
        WHERE database = %(database)s
          AND table = 'events'
          AND default_kind = 'MATERIALIZED'
          AND comment LIKE '%column_materializer::%'
    """,
        {"database": CLICKHOUSE_DATABASE, "table": table},
    )

    return {extract_property(comment): column_name for comment, column_name in rows}


def extract_property(comment: str) -> Property:
    return comment.split("::", 1)[1]
