from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.sessions_v3 import (
    DISTRIBUTED_RAW_SESSIONS_TABLE_SQL_V3,
    DROP_RAW_SESSION_DISTRIBUTED_TABLE_SQL_V3,
    DROP_RAW_SESSION_SHARDED_TABLE_SQL_V3,
    DROP_RAW_SESSION_VIEW_SQL_V3,
    DROP_RAW_SESSION_WRITABLE_TABLE_SQL_V3,
    RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL_V3,
    SHARDED_RAW_SESSIONS_TABLE_SQL_V3,
    WRITABLE_RAW_SESSIONS_TABLE_SQL_V3,
)

operations = [
    # drop in reverse order
    run_sql_with_exceptions(DROP_RAW_SESSION_VIEW_SQL_V3()),
    run_sql_with_exceptions(
        DROP_RAW_SESSION_DISTRIBUTED_TABLE_SQL_V3(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    run_sql_with_exceptions(DROP_RAW_SESSION_WRITABLE_TABLE_SQL_V3()),
    run_sql_with_exceptions(DROP_RAW_SESSION_SHARDED_TABLE_SQL_V3()),
    # recreate
    run_sql_with_exceptions(SHARDED_RAW_SESSIONS_TABLE_SQL_V3(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(WRITABLE_RAW_SESSIONS_TABLE_SQL_V3(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DISTRIBUTED_RAW_SESSIONS_TABLE_SQL_V3(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(
        RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL_V3(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
]
