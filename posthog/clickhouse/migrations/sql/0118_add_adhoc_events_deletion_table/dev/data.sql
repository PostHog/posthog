CREATE TABLE IF NOT EXISTS adhoc_events_deletion 
(
    team_id Int64,
    uuid UUID,
    created_at DateTime64(6, 'UTC') DEFAULT now64(),
    deleted_at DateTime,
    is_deleted UInt8 DEFAULT 0
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.adhoc_events_deletion', '{replica}-{shard}', deleted_at, is_deleted)
order by (team_id, uuid)
TTL deleted_at + INTERVAL 3 MONTH WHERE is_deleted = 1
