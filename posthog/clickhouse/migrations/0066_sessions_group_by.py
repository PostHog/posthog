from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.sessions_v2 import RAW_SESSION_TABLE_UPDATE_SQL

operations = [
    run_sql_with_exceptions(RAW_SESSION_TABLE_UPDATE_SQL()),
]
