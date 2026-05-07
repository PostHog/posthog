CREATE TABLE IF NOT EXISTS writable_duplicate_events
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

) ENGINE = Distributed('posthog_single_shard', 'default', 'duplicate_events')

CREATE TABLE IF NOT EXISTS kafka_duplicate_events
(
    team_id Int64,
    distinct_id String,
    event String,
    source_uuid UUID,
    duplicate_uuid UUID,
    similarity_score Float64,
    dedup_type LowCardinality(String),
    is_confirmed UInt8,
    reason Nullable(String),
    version String,
    different_property_count UInt32,
    properties_similarity Float64,
    source_message String,
    duplicate_message String,
    distinct_fields String,  -- JSON array as string from Kafka
    inserted_at DateTime64(3, 'UTC')
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_ingestion_events_duplicates', kafka_group_name = 'clickhouse_duplicate_events', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS duplicate_events_mv
TO writable_duplicate_events
AS SELECT
team_id,
distinct_id,
event,
source_uuid,
duplicate_uuid,
similarity_score,
dedup_type,
is_confirmed,
reason,
version,
different_property_count,
properties_similarity,
source_message,
duplicate_message,
JSONExtract(distinct_fields, 'Array(Tuple(field_name String, original_value String, new_value String))') as distinct_fields,
inserted_at,
_timestamp,
_offset,
_partition
FROM default.kafka_duplicate_events
