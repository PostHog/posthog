"""
Drop unused test/debug tables that only exist in dev environments.

These tables were created via migrations that either used ON CLUSTER syntax
(incompatible with our migration framework) or were test tables that were
never meant for production. The Kafka topics exist on all clusters but the
ClickHouse consumers only exist in dev.

This migration cleans up:

1. partition_statistics infrastructure (migrations 0041, 0042, 0062)
   - Consumer group: partition_statistics
   - Topics: events_plugin_ingestion, events_plugin_ingestion_historical,
     events_plugin_ingestion_overflow, session_recording_events,
     session_recording_snapshot_item_events, session_recording_snapshot_item_overflow

2. session_replay_events_v2_test (migration 0097, partially dropped in 0146)
   - Consumer group: clickhouse_session_replay_events_v2_test
   - Topic: session_replay_events_v2_test

3. log_entries_v2_test (migration 0110)
   - Consumer group: group1
   - Topic: log_entries_v2_test
"""

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# =============================================================================
# 1. PARTITION STATISTICS (from migrations 0041, 0042, 0062)
# =============================================================================

# Materialized views (v2) - adding max_table_size_to_drop = 0 for safety
DROP_MV_PARTITION_STATS = [
    "DROP TABLE IF EXISTS events_plugin_ingestion_partition_statistics_v2_mv SETTINGS max_table_size_to_drop = 0",
    "DROP TABLE IF EXISTS events_plugin_ingestion_overflow_partition_statistics_v2_mv SETTINGS max_table_size_to_drop = 0",
    "DROP TABLE IF EXISTS events_plugin_ingestion_historical_partition_statistics_v2_mv SETTINGS max_table_size_to_drop = 0",
    "DROP TABLE IF EXISTS session_recording_snapshot_item_events_partition_statistics_v2_mv SETTINGS max_table_size_to_drop = 0",
    "DROP TABLE IF EXISTS session_recording_snapshot_item_overflow_partition_statistics_v2_mv SETTINGS max_table_size_to_drop = 0",
]

# Kafka tables (consumer group: partition_statistics)
# Note: Kafka tables shouldn't store data but adding max_table_size_to_drop = 0 for safety
DROP_KAFKA_PARTITION_STATS = [
    "DROP TABLE IF EXISTS kafka_events_plugin_ingestion_partition_statistics SETTINGS max_table_size_to_drop = 0",
    "DROP TABLE IF EXISTS kafka_events_plugin_ingestion_overflow_partition_statistics SETTINGS max_table_size_to_drop = 0",
    "DROP TABLE IF EXISTS kafka_events_plugin_ingestion_historical_partition_statistics SETTINGS max_table_size_to_drop = 0",
    "DROP TABLE IF EXISTS kafka_session_recording_events_partition_statistics SETTINGS max_table_size_to_drop = 0",
    "DROP TABLE IF EXISTS kafka_session_recording_snapshot_item_events_partition_statistics SETTINGS max_table_size_to_drop = 0",
    "DROP TABLE IF EXISTS kafka_session_recording_snapshot_item_overflow_partition_statistics SETTINGS max_table_size_to_drop = 0",
]

# Destination table
DROP_TABLE_PARTITION_STATS = (
    "DROP TABLE IF EXISTS events_plugin_ingestion_partition_statistics_v2 SYNC SETTINGS max_table_size_to_drop = 0"
)

# =============================================================================
# 2. SESSION REPLAY EVENTS V2 TEST (from migration 0097, partial cleanup in 0146)
# =============================================================================

# MV, Kafka table, and data tables - all with max_table_size_to_drop = 0 for safety
DROP_SESSION_REPLAY_V2_TEST = [
    "DROP TABLE IF EXISTS session_replay_events_v2_test_mv SETTINGS max_table_size_to_drop = 0",
    "DROP TABLE IF EXISTS kafka_session_replay_events_v2_test SETTINGS max_table_size_to_drop = 0",
    "DROP TABLE IF EXISTS writable_session_replay_events_v2_test SETTINGS max_table_size_to_drop = 0",
    "DROP TABLE IF EXISTS session_replay_events_v2_test SETTINGS max_table_size_to_drop = 0",
]

# Sharded table
DROP_SESSION_REPLAY_V2_TEST_SHARDED = (
    "DROP TABLE IF EXISTS sharded_session_replay_events_v2_test SETTINGS max_table_size_to_drop = 0"
)

# =============================================================================
# 3. LOG ENTRIES V2 TEST (from migration 0110)
# =============================================================================

DROP_LOG_ENTRIES_V2_TEST = [
    "DROP TABLE IF EXISTS log_entries_v2_test_mv SETTINGS max_table_size_to_drop = 0",
    "DROP TABLE IF EXISTS kafka_log_entries_v2_test SETTINGS max_table_size_to_drop = 0",
    "DROP TABLE IF EXISTS log_entries_v2_test SYNC SETTINGS max_table_size_to_drop = 0",
]

# =============================================================================
# OPERATIONS
# =============================================================================

operations = []

# 1. Partition statistics cleanup
for sql in DROP_MV_PARTITION_STATS:
    operations.append(run_sql_with_exceptions(sql, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]))

for sql in DROP_KAFKA_PARTITION_STATS:
    operations.append(run_sql_with_exceptions(sql, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]))

operations.append(run_sql_with_exceptions(DROP_TABLE_PARTITION_STATS, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]))

# 2. Session replay events v2 test cleanup
for sql in DROP_SESSION_REPLAY_V2_TEST:
    operations.append(run_sql_with_exceptions(sql, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]))

# Sharded table only exists on DATA nodes
operations.append(run_sql_with_exceptions(DROP_SESSION_REPLAY_V2_TEST_SHARDED, node_roles=[NodeRole.DATA]))

# 3. Log entries v2 test cleanup
for sql in DROP_LOG_ENTRIES_V2_TEST:
    operations.append(run_sql_with_exceptions(sql, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]))
