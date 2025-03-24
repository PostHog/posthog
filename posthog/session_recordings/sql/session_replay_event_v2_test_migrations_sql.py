from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.session_recordings.sql.session_replay_event_v2_test_sql import (
    SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE,
)

# This migration adds columns that exist in the main session_replay_events table
# but are missing from the v2 test table. All columns are added with default values
# instead of being nullable, to maintain data consistency.
ALTER_SESSION_REPLAY_V2_TEST_ADD_MISSING_COLUMNS = """
    ALTER TABLE {table_name} {on_cluster_clause}
        ADD COLUMN IF NOT EXISTS first_url AggregateFunction(argMin, Nullable(VARCHAR), DateTime64(6, 'UTC')),
        ADD COLUMN IF NOT EXISTS all_urls SimpleAggregateFunction(groupUniqArrayArray, Array(String)) DEFAULT [],
        ADD COLUMN IF NOT EXISTS click_count SimpleAggregateFunction(sum, Int64) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS keypress_count SimpleAggregateFunction(sum, Int64) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS mouse_activity_count SimpleAggregateFunction(sum, Int64) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS active_milliseconds SimpleAggregateFunction(sum, Int64) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS console_log_count SimpleAggregateFunction(sum, Int64) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS console_warn_count SimpleAggregateFunction(sum, Int64) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS console_error_count SimpleAggregateFunction(sum, Int64) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS size SimpleAggregateFunction(sum, Int64) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS message_count SimpleAggregateFunction(sum, Int64) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS event_count SimpleAggregateFunction(sum, Int64) DEFAULT 0,
        ADD COLUMN IF NOT EXISTS snapshot_source AggregateFunction(argMin, LowCardinality(Nullable(String)), DateTime64(6, 'UTC')),
        ADD COLUMN IF NOT EXISTS snapshot_library AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
        ADD COLUMN IF NOT EXISTS _timestamp SimpleAggregateFunction(max, DateTime) DEFAULT toDateTime(0)
"""

# Drop the materialized view
DROP_SESSION_REPLAY_EVENTS_V2_TEST_MV_SQL_TEMPLATE = """
    DROP TABLE IF EXISTS session_replay_events_v2_test_mv {on_cluster_clause}
"""

# Drop the Kafka table
DROP_KAFKA_SESSION_REPLAY_EVENTS_V2_TEST_SQL_TEMPLATE = """
    DROP TABLE IF EXISTS kafka_session_replay_events_v2_test {on_cluster_clause}
"""

# Remove the low cardinality constraint from the snapshot_source column
REMOVE_SNAPSHOT_SOURCE_LOW_CARDINALITY_SQL_TEMPLATE = """
    ALTER TABLE {table_name} {on_cluster_clause}
        MODIFY COLUMN `snapshot_source` AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))
"""


def ADD_MISSING_COLUMNS_DISTRIBUTED_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL(on_cluster=True):
    return ALTER_SESSION_REPLAY_V2_TEST_ADD_MISSING_COLUMNS.format(
        table_name="session_replay_events_v2_test",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )


def ADD_MISSING_COLUMNS_WRITABLE_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL(on_cluster=True):
    return ALTER_SESSION_REPLAY_V2_TEST_ADD_MISSING_COLUMNS.format(
        table_name="writable_session_replay_events_v2_test",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )


def ADD_MISSING_COLUMNS_SHARDED_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL(on_cluster=True):
    return ALTER_SESSION_REPLAY_V2_TEST_ADD_MISSING_COLUMNS.format(
        table_name=SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )


def DROP_SESSION_REPLAY_EVENTS_V2_TEST_MV_TABLE_SQL(on_cluster=True):
    return DROP_SESSION_REPLAY_EVENTS_V2_TEST_MV_SQL_TEMPLATE.format(
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )


def DROP_KAFKA_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL(on_cluster=True):
    return DROP_KAFKA_SESSION_REPLAY_EVENTS_V2_TEST_SQL_TEMPLATE.format(
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )


def REMOVE_SNAPSHOT_SOURCE_LOW_CARDINALITY_SQL(on_cluster=True):
    return REMOVE_SNAPSHOT_SOURCE_LOW_CARDINALITY_SQL_TEMPLATE.format(
        table_name=SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )
