from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Migration to drop the distinct_id_usage tables.
#
# The original migration (0195) created distinct_id_usage as a non-sharded replicated table,
# but the MV reads from sharded_events which is sharded. This caused replication issues
# because inserts to sharded_events trigger the MV on each shard, but the destination
# table wasn't sharded.
#
# Additionally, attaching an MV to the events write path adds dependencies that can
# impact ingestion performance. A future migration will recreate this table with a
# separate Kafka engine that reads from the events topic directly.
#
# This migration only performs cleanup - dropping all distinct_id_usage objects.

operations = [
    # 1. Drop the MV on data nodes (where it was created)
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS distinct_id_usage_mv",
        node_roles=[NodeRole.DATA],
    ),
    # 2. Drop the writable distributed table on data nodes
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS writable_distinct_id_usage",
        node_roles=[NodeRole.DATA],
    ),
    # 3. Drop the data table on all nodes
    # Use SYNC because it was a replicated table
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS distinct_id_usage SYNC",
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
