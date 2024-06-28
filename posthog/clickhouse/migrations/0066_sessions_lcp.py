from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.sql import (
    RAW_SESSIONS_TABLE_MV_SQL,
    DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL,
    DROP_RAW_SESSION_VIEW_SQL,
    RAW_SESSIONS_VIEW_SQL,
)
from posthog.settings import CLICKHOUSE_CLUSTER
from infi.clickhouse_orm import migrations

ADD_LCP_COLUMNS_BASE_SQL = """
ALTER TABLE {table}
ON CLUSTER {cluster}
ADD COLUMN IF NOT EXISTS first_lcp AggregateFunction(argMin, Nullable(Float64), DateTime64(6, 'UTC'))
"""


DROP_PAGEVIEW_COLUMN_BASE_SQL = """
ALTER TABLE {table}
ON CLUSTER {cluster}
DROP COLUMN IF EXISTS pageview_count
"""

DROP_SCREEN_COLUMN_BASE_SQL = """
ALTER TABLE {table}
ON CLUSTER {cluster}
DROP COLUMN IF EXISTS screen_count
"""

DROP_AUTOCAPTURE_COLUMN_BASE_SQL = """
ALTER TABLE {table}
ON CLUSTER {cluster}
DROP COLUMN IF EXISTS autocapture_count
"""


def add_columns_to_required_tables(_):
    sync_execute(ADD_LCP_COLUMNS_BASE_SQL.format(table="raw_sessions", cluster=CLICKHOUSE_CLUSTER))
    sync_execute(ADD_LCP_COLUMNS_BASE_SQL.format(table="sharded_raw_sessions", cluster=CLICKHOUSE_CLUSTER))


def drop_columns_from_required_tables(_):
    for sql in [DROP_PAGEVIEW_COLUMN_BASE_SQL, DROP_SCREEN_COLUMN_BASE_SQL, DROP_AUTOCAPTURE_COLUMN_BASE_SQL]:
        sync_execute(sql.format(table="raw_sessions", cluster=CLICKHOUSE_CLUSTER))
        sync_execute(sql.format(table="sharded_raw_sessions", cluster=CLICKHOUSE_CLUSTER))


operations = [
    # drop the MV and view, will prevent the underlying table from getting new events, so make sure that the time this is run is backfilled
    run_sql_with_exceptions(DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL),
    run_sql_with_exceptions(DROP_RAW_SESSION_VIEW_SQL),
    migrations.RunPython(add_columns_to_required_tables),
    migrations.RunPython(drop_columns_from_required_tables),
    # add the MV and view back
    run_sql_with_exceptions(RAW_SESSIONS_TABLE_MV_SQL),
    run_sql_with_exceptions(RAW_SESSIONS_VIEW_SQL),
]
