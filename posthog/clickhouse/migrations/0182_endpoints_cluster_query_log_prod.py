from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    QUERY_LOG_ARCHIVE_CROSS_CLUSTER_DISTRIBUTED_TABLE_SQL,
    QUERY_LOG_ARCHIVE_NEW_MV_SQL,
    QUERY_LOG_ARCHIVE_WRITABLE_DISTRIBUTED_TABLE,
)

operations = [
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_CROSS_CLUSTER_DISTRIBUTED_TABLE_SQL(),
        node_roles=NodeRole.ENDPOINTS,
    ),
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_NEW_MV_SQL(
            view_name="query_log_archive_mv", dest_table=QUERY_LOG_ARCHIVE_WRITABLE_DISTRIBUTED_TABLE
        ),
        node_roles=NodeRole.ENDPOINTS,
    ),
]
