DROP TABLE IF EXISTS pg_embeddings SYNC

CREATE TABLE IF NOT EXISTS pg_embeddings 
(
    domain String,
    team_id Int64,
    id String,
    vector Array(Float32),
    text String,
    properties VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC') DEFAULT NOW('UTC'),
    is_deleted UInt8,
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.pg_embeddings', '{replica}-{shard}', timestamp, is_deleted)

    -- id for uniqueness
    ORDER BY (team_id, domain, id)
    SETTINGS index_granularity=512
