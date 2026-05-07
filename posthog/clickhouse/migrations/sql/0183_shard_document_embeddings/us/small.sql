DROP TABLE IF EXISTS posthog_document_embeddings_mv

DROP TABLE IF EXISTS kafka_posthog_document_embeddings

DROP TABLE IF EXISTS writable_posthog_document_embeddings

CREATE TABLE IF NOT EXISTS writable_posthog_document_embeddings
(
    team_id Int64,
    product LowCardinality(String), -- Like "error tracking" or "session replay" - basically a bucket, you'd use this to ask clickhouse "what kind of documents do I have embeddings for, related to session replay"
    document_type LowCardinality(String), -- The type of document this is an embedding for, e.g. "issue_fingerprint", "session_summary", "task_update" etc.
    model_name LowCardinality(String), -- The name of the model used to generate this embedding. Includes embedding dimensionality, appended as e.g. "text-embedding-3-small-1024"
    rendering LowCardinality(String), -- How the document was rendered to text, e.g. "with_error_message", "as_html" etc. Use "plain" if it was already text.
    document_id String, -- A uuid, a path like "issue/<chunk_id>", whatever you like really
    timestamp DateTime64(3, 'UTC'), -- This is a user defined timestamp, meant to be the /documents/ creation time (or similar), rather than the time the embedding was created
    inserted_at DateTime64(3, 'UTC'), -- When was this embedding inserted (if a duplicate-key row was inserted, for example, this is what we use to choose the winner)
    content String DEFAULT '', -- The actual text content that was embedded
    metadata String DEFAULT '{}', -- JSON metadata for the document, stored as a string
    embedding Array(Float64) -- The embedding itself
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

) ENGINE = Distributed('posthog', 'default', 'partitioned_sharded_posthog_document_embeddings', cityHash64(document_id))

CREATE TABLE IF NOT EXISTS kafka_posthog_document_embeddings
(
    team_id Int64,
    product LowCardinality(String), -- Like "error tracking" or "session replay" - basically a bucket, you'd use this to ask clickhouse "what kind of documents do I have embeddings for, related to session replay"
    document_type LowCardinality(String), -- The type of document this is an embedding for, e.g. "issue_fingerprint", "session_summary", "task_update" etc.
    model_name LowCardinality(String), -- The name of the model used to generate this embedding. Includes embedding dimensionality, appended as e.g. "text-embedding-3-small-1024"
    rendering LowCardinality(String), -- How the document was rendered to text, e.g. "with_error_message", "as_html" etc. Use "plain" if it was already text.
    document_id String, -- A uuid, a path like "issue/<chunk_id>", whatever you like really
    timestamp DateTime64(3, 'UTC'), -- This is a user defined timestamp, meant to be the /documents/ creation time (or similar), rather than the time the embedding was created
    inserted_at DateTime64(3, 'UTC'), -- When was this embedding inserted (if a duplicate-key row was inserted, for example, this is what we use to choose the winner)
    content String, -- The actual text content that was embedded
    metadata String, -- JSON metadata for the document, stored as a string
    embedding Array(Float64) -- The embedding itself
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_document_embeddings', kafka_group_name = 'clickhouse_document_embeddings2', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS posthog_document_embeddings_mv
TO writable_posthog_document_embeddings
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
