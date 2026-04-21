from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Migration 0222 added this index but used is_alter_on_replicated_table=True, which routed
# through map_one_host_per_shard. In prod-us only a subset of shards had the ALTER applied
# (4 out of 10 shards ended up with the index). Re-run with sharded=True only, matching
# the pattern used by migration 0109 for the underlying column — this runs on every DATA
# node, and IF NOT EXISTS + ReplicatedMergeTree's ZooKeeper-backed ALTER dedup make it
# safe to apply on shards that already have the index.
ADD_MINMAX_INDEX_SHARDED_EVENTS = """
ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS `minmax_$session_id_uuid` `$session_id_uuid`
TYPE minmax
GRANULARITY 1
"""

operations = [
    run_sql_with_exceptions(
        ADD_MINMAX_INDEX_SHARDED_EVENTS,
        sharded=True,
        is_alter_on_replicated_table=False,
    ),
]
