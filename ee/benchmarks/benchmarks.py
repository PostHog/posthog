# Needs to be first to set up django environment
from .helpers import *

from datetime import timedelta
from typing import List, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.materialized_columns import backfill_materialized_columns, get_materialized_columns, materialize
from posthog.models.property import PropertyName, TableWithProperties

# :TODO: Raise an error if not in right environment?
# :TODO: Manipulate materialized properties somehow?

MATERIALIZED_PROPERTIES: List[Tuple[TableWithProperties, PropertyName]] = [("events", "$host"), ("person", "email")]


class QuerySuite:
    def setup(self):
        for table, property in MATERIALIZED_PROPERTIES:
            if property not in get_materialized_columns(table):
                materialize(table, property)
                backfill_materialized_columns(table, [property], backfill_period=timedelta(days=1_000))

    @benchmark_clickhouse
    def track_foobar(self):
        print(sync_execute("SELECT count(*) FROM events WHERE event = '$pageview'"))
