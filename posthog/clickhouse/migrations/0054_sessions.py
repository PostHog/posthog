from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.sessions.sql import (
    DISTRIBUTED_SESSIONS_TABLE_SQL,
    SESSIONS_TABLE_MV_SQL,
    SESSIONS_TABLE_SQL,
    SESSIONS_VIEW_SQL,
    WRITABLE_SESSIONS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(WRITABLE_SESSIONS_TABLE_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_SESSIONS_TABLE_SQL()),
    run_sql_with_exceptions(SESSIONS_TABLE_SQL()),
    run_sql_with_exceptions(SESSIONS_TABLE_MV_SQL()),
    run_sql_with_exceptions(SESSIONS_VIEW_SQL()),
]
