from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    QUERY_LOG_ARCHIVE_NEW_TABLE_SQL,
    QUERY_LOG_ARCHIVE_NEW_MV,
)

operations = [
    # Step 1: Create new table with team_id in ordering key
    run_sql_with_exceptions(QUERY_LOG_ARCHIVE_NEW_TABLE_SQL(on_cluster=False), node_role=NodeRole.ALL),
    # Step 2: Create new materialized view to populate the new table
    run_sql_with_exceptions(QUERY_LOG_ARCHIVE_NEW_MV(on_cluster=False), node_role=NodeRole.ALL),
]
