from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.heatmaps.sql import ALTER_TABLE_ADD_TTL_PERIOD

"""
heatmaps table is compressing at >70% but we don't want it to grow unbounded
so we are adding a TTL to it
"""
operations = [
    run_sql_with_exceptions(ALTER_TABLE_ADD_TTL_PERIOD()),
]
