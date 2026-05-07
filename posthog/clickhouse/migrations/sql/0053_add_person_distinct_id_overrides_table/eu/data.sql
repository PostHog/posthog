CREATE TABLE IF NOT EXISTS person_distinct_id_overrides ON CLUSTER 'posthog'
(
    team_id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    is_deleted Int8,
    version Int64
    
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

    , INDEX kafka_timestamp_minmax_person_distinct_id_overrides _timestamp TYPE minmax GRANULARITY 3
    
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.person_distinct_id_overrides', '{replica}-{shard}', version)

    ORDER BY (team_id, distinct_id)
    SETTINGS index_granularity = 512
