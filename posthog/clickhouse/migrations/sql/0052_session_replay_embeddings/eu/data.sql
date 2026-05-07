CREATE TABLE IF NOT EXISTS writable_session_replay_embeddings ON CLUSTER 'posthog'
(
    -- part of order by so will aggregate correctly
    session_id VARCHAR,
    -- part of order by so will aggregate correctly
    team_id Int64,
    embeddings Array(Float32),
    generation_timestamp DateTime64(6, 'UTC') DEFAULT NOW('UTC'),
    -- we will insert directly for the first test of this
    -- so no _timestamp or _offset column
    --_timestamp SimpleAggregateFunction(max, DateTime)
) ENGINE = Distributed('posthog', 'default', 'sharded_session_replay_embeddings', sipHash64(session_id))

CREATE TABLE IF NOT EXISTS session_replay_embeddings ON CLUSTER 'posthog'
(
    -- part of order by so will aggregate correctly
    session_id VARCHAR,
    -- part of order by so will aggregate correctly
    team_id Int64,
    embeddings Array(Float32),
    generation_timestamp DateTime64(6, 'UTC') DEFAULT NOW('UTC'),
    -- we will insert directly for the first test of this
    -- so no _timestamp or _offset column
    --_timestamp SimpleAggregateFunction(max, DateTime)
) ENGINE = Distributed('posthog', 'default', 'sharded_session_replay_embeddings', sipHash64(session_id))

CREATE TABLE IF NOT EXISTS sharded_session_replay_embeddings ON CLUSTER 'posthog'
(
    -- part of order by so will aggregate correctly
    session_id VARCHAR,
    -- part of order by so will aggregate correctly
    team_id Int64,
    embeddings Array(Float32),
    generation_timestamp DateTime64(6, 'UTC') DEFAULT NOW('UTC'),
    -- we will insert directly for the first test of this
    -- so no _timestamp or _offset column
    --_timestamp SimpleAggregateFunction(max, DateTime)
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/posthog.session_replay_embeddings', '{replica}')

    PARTITION BY toYYYYMM(generation_timestamp)
    -- order by must be in order of increasing cardinality
    -- so we order by date first, then team_id, then session_id
    -- hopefully, this is a good balance between the two
    ORDER BY (toDate(generation_timestamp), team_id, session_id)
    -- we don't want to keep embeddings forever, so we will set a TTL
    -- the max any individual recording could survive is 1 year, so...
    TTL toDate(generation_timestamp) + INTERVAL 1 YEAR
SETTINGS index_granularity=512
