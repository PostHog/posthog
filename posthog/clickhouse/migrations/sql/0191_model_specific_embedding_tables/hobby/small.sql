CREATE TABLE IF NOT EXISTS writable_posthog_document_embeddings_buffer
(
    team_id Int64,
    product LowCardinality(String),
    document_type LowCardinality(String),
    model_name LowCardinality(String),  -- Used for filtering in model-specific MVs
    rendering LowCardinality(String),
    document_id String,
    timestamp DateTime64(3, 'UTC'),
    inserted_at DateTime64(3, 'UTC'),
    content String DEFAULT '',
    metadata String DEFAULT '{}',
    embedding Array(Float64)
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

) ENGINE = Distributed('posthog', 'default', 'sharded_posthog_document_embeddings_buffer', cityHash64(document_id))

CREATE MATERIALIZED VIEW IF NOT EXISTS posthog_document_embeddings_kafka_to_buffer_mv
TO writable_posthog_document_embeddings_buffer
AS SELECT
team_id,
product,
document_type,
model_name,
rendering,
document_id,
timestamp,
_timestamp as inserted_at,
coalesce(content, '') as content,
coalesce(metadata, '{}') as metadata,
embedding,
_timestamp,
_offset,
_partition
FROM default.kafka_posthog_document_embeddings
