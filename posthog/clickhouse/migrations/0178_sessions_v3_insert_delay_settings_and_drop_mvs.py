from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.sessions_v3 import (
    ALTER_SHARDED_RAW_SESSIONS_TABLE_SETTINGS_V3,
    DROP_RAW_SESSION_MATERIALIZED_VIEW_RECORDINGS_SQL_V3,
    DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL_V3,
)

operations = [
    run_sql_with_exceptions(
        ALTER_SHARDED_RAW_SESSIONS_TABLE_SETTINGS_V3(),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL_V3(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_RAW_SESSION_MATERIALIZED_VIEW_RECORDINGS_SQL_V3(), node_roles=[NodeRole.DATA]),
]
