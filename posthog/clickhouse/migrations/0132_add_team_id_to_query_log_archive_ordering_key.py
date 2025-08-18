from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    QUERY_LOG_ARCHIVE_NEW_TABLE_SQL,
    QUERY_LOG_ARCHIVE_NEW_MV,
    INSERT_HISTORICAL_DATA_TO_QUERY_LOG_ARCHIVE_NEW,
    INSERT_TRANSITION_PERIOD_DATA_TO_QUERY_LOG_ARCHIVE_NEW,
    DROP_QUERY_LOG_ARCHIVE_MV,
    RENAME_QUERY_LOG_ARCHIVE_TABLES,
    RENAME_QUERY_LOG_ARCHIVE_MV,
    DROP_QUERY_LOG_ARCHIVE_OLD_TABLE,
)

operations = [
    # Step 1: Create new table with team_id in ordering key
    run_sql_with_exceptions(QUERY_LOG_ARCHIVE_NEW_TABLE_SQL(on_cluster=False), node_role=NodeRole.ALL),
    # Step 2: Create new materialized view to populate the new table
    run_sql_with_exceptions(QUERY_LOG_ARCHIVE_NEW_MV(on_cluster=False), node_role=NodeRole.ALL),
    # Step 3: Get the earliest event_time in the new table (if any)
    # and insert historical data from old table
    run_sql_with_exceptions(INSERT_HISTORICAL_DATA_TO_QUERY_LOG_ARCHIVE_NEW(), node_role=NodeRole.ALL),
    # Step 4: Handle transition period with deduplication
    # Insert records from the transition period that don't exist in the new table
    run_sql_with_exceptions(INSERT_TRANSITION_PERIOD_DATA_TO_QUERY_LOG_ARCHIVE_NEW(), node_role=NodeRole.ALL),
    # Step 5: Drop the old materialized view
    run_sql_with_exceptions(DROP_QUERY_LOG_ARCHIVE_MV(on_cluster=False), node_role=NodeRole.ALL),
    # Step 6: Rename tables (atomic swap)
    run_sql_with_exceptions(RENAME_QUERY_LOG_ARCHIVE_TABLES(on_cluster=False), node_role=NodeRole.ALL),
    # Step 7: Rename the new materialized view
    run_sql_with_exceptions(RENAME_QUERY_LOG_ARCHIVE_MV(on_cluster=False), node_role=NodeRole.ALL),
    # Step 8: Drop the old table
    run_sql_with_exceptions(DROP_QUERY_LOG_ARCHIVE_OLD_TABLE(on_cluster=False), node_role=NodeRole.ALL),
]
