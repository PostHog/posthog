from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.migrations import (
    DISTRIBUTED_RAW_SESSIONS_ADD_EPIK_QCLID_SCCID_COLUMNS_SQL,
    SHARDED_RAW_SESSIONS_ADD_EPIK_QCLID_SCCID_COLUMNS_SQL,
    WRITABLE_RAW_SESSIONS_ADD_EPIK_QCLID_SCCID_COLUMNS_SQL,
)
from posthog.models.raw_sessions.sql import (
    DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL,
    RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL,
    RAW_SESSIONS_TABLE_MV_SQL,
)

operations = [
    # Drop the MV first to avoid insertions during migration
    run_sql_with_exceptions(DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL(), node_role=NodeRole.DATA),
    # Modify tables
    run_sql_with_exceptions(
        SHARDED_RAW_SESSIONS_ADD_EPIK_QCLID_SCCID_COLUMNS_SQL(), node_role=NodeRole.DATA, sharded=True
    ),
    run_sql_with_exceptions(DISTRIBUTED_RAW_SESSIONS_ADD_EPIK_QCLID_SCCID_COLUMNS_SQL(), node_role=NodeRole.ALL),
    run_sql_with_exceptions(WRITABLE_RAW_SESSIONS_ADD_EPIK_QCLID_SCCID_COLUMNS_SQL(), node_role=NodeRole.DATA),
    # Recreate view and MV
    run_sql_with_exceptions(RAW_SESSIONS_TABLE_MV_SQL(), node_role=NodeRole.DATA),
    run_sql_with_exceptions(RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL(), node_role=NodeRole.ALL),
]
