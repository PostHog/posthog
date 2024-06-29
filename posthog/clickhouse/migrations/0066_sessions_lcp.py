from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.sql import (
    RAW_SESSIONS_TABLE_MV_SQL,
    DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL,
    DROP_RAW_SESSION_VIEW_SQL,
    RAW_SESSIONS_VIEW_SQL,
)
from posthog.settings import CLICKHOUSE_CLUSTER

ADD_LCP_COLUMN_BASE_SQL = """
ALTER TABLE {table}
ON CLUSTER {cluster}
ADD COLUMN IF NOT EXISTS first_lcp AggregateFunction(argMin, Nullable(Float64), DateTime64(6, 'UTC'))
"""


operations = [
    # drop the MV and view, will prevent the underlying table from getting new events, so make sure that the time this is run is backfilled
    run_sql_with_exceptions(DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL),
    run_sql_with_exceptions(DROP_RAW_SESSION_VIEW_SQL),
    # add the column
    run_sql_with_exceptions(ADD_LCP_COLUMN_BASE_SQL.format(table="raw_sessions", cluster=CLICKHOUSE_CLUSTER)),
    run_sql_with_exceptions(ADD_LCP_COLUMN_BASE_SQL.format(table="writeable_sessions", cluster=CLICKHOUSE_CLUSTER)),
    run_sql_with_exceptions(ADD_LCP_COLUMN_BASE_SQL.format(table="sharded_raw_sessions", cluster=CLICKHOUSE_CLUSTER)),
    # add the MV and view back
    run_sql_with_exceptions(RAW_SESSIONS_TABLE_MV_SQL),
    run_sql_with_exceptions(RAW_SESSIONS_VIEW_SQL),
]
