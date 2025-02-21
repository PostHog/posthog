from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.migrations import (
    BASE_RAW_SESSIONS_ADD_IRCLID_KX_COLUMNS_SQL,
    DISTRIBUTED_RAW_SESSIONS_ADD_IRCLID_KX_COLUMNS_SQL,
    WRITABLE_RAW_SESSIONS_ADD_IRCLID_KX_COLUMNS_SQL,
)
from posthog.models.raw_sessions.sql import (
    DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL,
    RAW_SESSIONS_TABLE_MV_SQL,
    RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL,
)

operations = [
    # drop the mv, so we are no longer receiving events from the sessions table
    run_sql_with_exceptions(DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL()),
    # now we can alter the target tables
    run_sql_with_exceptions(BASE_RAW_SESSIONS_ADD_IRCLID_KX_COLUMNS_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_RAW_SESSIONS_ADD_IRCLID_KX_COLUMNS_SQL()),
    run_sql_with_exceptions(
        BASE_RAW_SESSIONS_ADD_IRCLID_KX_COLUMNS_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR
    ),
    run_sql_with_exceptions(WRITABLE_RAW_SESSIONS_ADD_IRCLID_KX_COLUMNS_SQL()),
    # and then recreate the materialized view and view
    run_sql_with_exceptions(RAW_SESSIONS_TABLE_MV_SQL()),
    run_sql_with_exceptions(RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL()),
]
