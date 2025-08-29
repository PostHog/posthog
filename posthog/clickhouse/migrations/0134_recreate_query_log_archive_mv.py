from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    DROP_QUERY_LOG_ARCHIVE_MV,
    QUERY_LOG_ARCHIVE_DATA_TABLE,
    QUERY_LOG_ARCHIVE_MV,
    QUERY_LOG_ARCHIVE_NEW_MV_SQL,
)

operations = [
    # Drop the old materialized view
    run_sql_with_exceptions(
        DROP_QUERY_LOG_ARCHIVE_MV(on_cluster=False),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_NEW_MV_SQL(
            view_name=QUERY_LOG_ARCHIVE_MV, dest_table=QUERY_LOG_ARCHIVE_DATA_TABLE, on_cluster=False
        ),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
