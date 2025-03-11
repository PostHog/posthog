from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.sql import (
    DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL,
    RAW_SESSIONS_TABLE_MV_SQL,
    RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL,
)

# Simply need to rebuild our sessions v2 view to get the new columns to show up
operations = [
    run_sql_with_exceptions(DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL()),
    run_sql_with_exceptions(RAW_SESSIONS_TABLE_MV_SQL()),
    run_sql_with_exceptions(RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL()),
]
