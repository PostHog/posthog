from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.sessions_v3 import RAW_SESSIONS_TABLE_MV_SQL_V3

operations = [
    run_sql_with_exceptions(RAW_SESSIONS_TABLE_MV_SQL_V3(), node_roles=[NodeRole.DATA], sharded=False),
]
