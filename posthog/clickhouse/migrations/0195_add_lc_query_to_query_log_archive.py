from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    QUERY_LOG_ARCHIVE_ADD_LC_QUERY_SQL,
    QUERY_LOG_ARCHIVE_MV_V4_SQL,
    QUERY_LOG_ARCHIVE_WRITABLE_DISTRIBUTED_TABLE,
)

operations = [
    # Add lc_query column to query_log_archive table
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_ADD_LC_QUERY_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        is_alter_on_replicated_table=True,
        sharded=False,
    ),
    # Add lc_query column to writable_query_log_archive distributed table
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_ADD_LC_QUERY_SQL(QUERY_LOG_ARCHIVE_WRITABLE_DISTRIBUTED_TABLE),
        node_roles=[NodeRole.ENDPOINTS],
        is_alter_on_replicated_table=False,
        sharded=False,
    ),
    # Update the MV to extract lc_query from log_comment
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_MV_V4_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR, NodeRole.ENDPOINTS],
        is_alter_on_replicated_table=False,
        sharded=False,
    ),
]
