from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.sql import (
    DISTRIBUTED_RAW_SESSIONS_TABLE_SQL,
    RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL,
    RAW_SESSIONS_TABLE_MV_SQL,
    RAW_SESSIONS_TABLE_SQL,
    WRITABLE_RAW_SESSIONS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(WRITABLE_RAW_SESSIONS_TABLE_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_RAW_SESSIONS_TABLE_SQL()),
    run_sql_with_exceptions(RAW_SESSIONS_TABLE_SQL()),
    run_sql_with_exceptions(RAW_SESSIONS_TABLE_MV_SQL()),
    run_sql_with_exceptions(RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL()),
]
