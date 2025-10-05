from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.sql_v3 import (
    DISTRIBUTED_RAW_SESSIONS_TABLE_SQL_V3,
    RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL_V3,
    RAW_SESSIONS_TABLE_SQL_V3,
    WRITABLE_RAW_SESSIONS_TABLE_SQL_V3,
)

operations = [
    run_sql_with_exceptions(WRITABLE_RAW_SESSIONS_TABLE_SQL_V3()),
    run_sql_with_exceptions(DISTRIBUTED_RAW_SESSIONS_TABLE_SQL_V3(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(RAW_SESSIONS_TABLE_SQL_V3()),
    run_sql_with_exceptions(RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL_V3()),
    # normally there would be SQL to add the MV here too, but at the moment we only want this table to backfill,
    # so let's not increase the load on the cluster just yet
]
