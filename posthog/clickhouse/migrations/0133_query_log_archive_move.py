from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    DROP_QUERY_LOG_ARCHIVE_MV,
    EXCHANGE_QUERY_LOG_ARCHIVE_TABLES,
    RENAME_QUERY_LOG_ARCHIVE_MV,
    DROP_QUERY_LOG_ARCHIVE_OLD_TABLE,
)

operations = [
    # Step 5: Drop the old materialized view
    run_sql_with_exceptions(DROP_QUERY_LOG_ARCHIVE_MV(on_cluster=False), node_role=NodeRole.ALL),
    # Step 6: Rename tables (atomic swap)
    run_sql_with_exceptions(EXCHANGE_QUERY_LOG_ARCHIVE_TABLES(on_cluster=False), node_role=NodeRole.ALL),
    # Step 7: Rename the new materialized view
    run_sql_with_exceptions(RENAME_QUERY_LOG_ARCHIVE_MV(on_cluster=False), node_role=NodeRole.ALL),
    # Step 8: Drop the old table
    run_sql_with_exceptions(DROP_QUERY_LOG_ARCHIVE_OLD_TABLE(on_cluster=False), node_role=NodeRole.ALL),
]
