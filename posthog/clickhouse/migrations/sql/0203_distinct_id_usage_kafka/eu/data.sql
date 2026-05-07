CREATE TABLE IF NOT EXISTS sharded_distinct_id_usage
(
    team_id Int64,
    distinct_id String,
    minute DateTime,
    event_count UInt64
) ENGINE = ReplicatedSummingMergeTree('/clickhouse/tables/{shard}/posthog.distinct_id_usage', '{replica}', (event_count))

PARTITION BY toYYYYMMDD(minute)
ORDER BY (team_id, minute, distinct_id)
TTL toDate(minute) + INTERVAL 7 DAY
SETTINGS ttl_only_drop_parts = 1

CREATE TABLE IF NOT EXISTS distinct_id_usage
(
    team_id Int64,
    distinct_id String,
    minute DateTime,
    event_count UInt64
) ENGINE = Distributed('posthog', 'default', 'sharded_distinct_id_usage', sipHash64(distinct_id))
