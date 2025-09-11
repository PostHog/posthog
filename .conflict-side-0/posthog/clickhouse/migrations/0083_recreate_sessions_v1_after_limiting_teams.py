from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.sessions.sql import DROP_SESSION_MATERIALIZED_VIEW_SQL, SESSIONS_TABLE_MV_SQL

operations = [
    # drop the mv, and recreate it with the new part of the WHERE clause
    run_sql_with_exceptions(DROP_SESSION_MATERIALIZED_VIEW_SQL()),
    run_sql_with_exceptions(SESSIONS_TABLE_MV_SQL()),
]
