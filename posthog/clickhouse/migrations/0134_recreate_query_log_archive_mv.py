from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    DROP_QUERY_LOG_ARCHIVE_MV,
    QUERY_LOG_ARCHIVE_NEW_MV,
)

operations = [
    # Drop the old materialized view
    run_sql_with_exceptions(
        DROP_QUERY_LOG_ARCHIVE_MV(on_cluster=False),
        node_role=NodeRole.ALL,
    ),
    run_sql_with_exceptions(
        QUERY_LOG_ARCHIVE_NEW_MV(view_name="query_log_archive_mv", dest_table="query_log_archive", on_cluster=False),
        node_role=NodeRole.ALL,
    ),
]
