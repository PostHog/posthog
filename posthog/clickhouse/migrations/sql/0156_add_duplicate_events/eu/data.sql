CREATE TABLE IF NOT EXISTS duplicate_events
(
    team_id Int64,
    distinct_id String,
    event String,
    source_uuid UUID,
    duplicate_uuid UUID,
    similarity_score Float64,
    dedup_type LowCardinality(String),  -- "timestamp" or "uuid"
    is_confirmed UInt8,
    reason Nullable(String),
    version String,
    different_property_count UInt32,
    properties_similarity Float64,
    source_message String,  -- JSON string of full event
    duplicate_message String,  -- JSON string of full event
    distinct_fields Array(Tuple(field_name String, original_value String, new_value String)),
    inserted_at DateTime64(3, 'UTC')
    
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

    , INDEX kafka_timestamp_minmax_duplicate_events _timestamp TYPE minmax GRANULARITY 3
    
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.duplicate_events', '{replica}-{shard}')

    PARTITION BY toYYYYMMDD(inserted_at)
    ORDER BY (team_id, distinct_id, event, inserted_at)
    TTL inserted_at + INTERVAL 7 DAY DELETE
    SETTINGS index_granularity = 512
