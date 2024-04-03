from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.sessions.sql import (
    SESSIONS_TABLE_MV_SQL,
)

operations = [
    run_sql_with_exceptions(SESSIONS_TABLE_MV_SQL),
]
