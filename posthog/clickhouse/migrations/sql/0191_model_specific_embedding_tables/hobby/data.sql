CREATE TABLE IF NOT EXISTS sharded_posthog_document_embeddings_buffer
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

) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_posthog_document_embeddings_buffer', '{replica}', inserted_at)
PARTITION BY toDate(inserted_at)
ORDER BY (inserted_at, model_name, cityHash64(document_id))
TTL inserted_at + INTERVAL 1 DAY
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1

CREATE TABLE IF NOT EXISTS sharded_posthog_document_embeddings_text_embedding_3_small_1536
(
    team_id Int64,
    product LowCardinality(String), -- Like "error tracking" or "session replay" - basically a bucket
    document_type LowCardinality(String), -- The type of document this is an embedding for
    rendering LowCardinality(String), -- How the document was rendered to text
    document_id String, -- A uuid, a path like "issue/<chunk_id>", whatever you like really
    timestamp DateTime64(3, 'UTC'), -- This is a user defined timestamp, meant to be the /documents/ creation time
    inserted_at DateTime64(3, 'UTC'), -- When was this embedding inserted
    content String DEFAULT '', -- The actual text content that was embedded
    metadata String DEFAULT '{}', -- JSON metadata for the document, stored as a string
    embedding Array(Float64) -- The embedding itself
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64
, INDEX kafka_timestamp_minmax_sharded_posthog_document_embeddings_text_embedding_3_small_1536 _timestamp TYPE minmax GRANULARITY 3, CONSTRAINT embedding_dimension_check CHECK length(embedding) = 1536
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_posthog_document_embeddings_text_embedding_3_small_1536', '{replica}', inserted_at)

    PARTITION BY toMonday(timestamp)
    ORDER BY (team_id, toDate(timestamp), product, document_type, rendering, cityHash64(document_id))
    TTL timestamp + INTERVAL 3 MONTH
    SETTINGS index_granularity = 512, ttl_only_drop_parts = 1

CREATE TABLE IF NOT EXISTS sharded_posthog_document_embeddings_text_embedding_3_large_3072
(
    team_id Int64,
    product LowCardinality(String), -- Like "error tracking" or "session replay" - basically a bucket
    document_type LowCardinality(String), -- The type of document this is an embedding for
    rendering LowCardinality(String), -- How the document was rendered to text
    document_id String, -- A uuid, a path like "issue/<chunk_id>", whatever you like really
    timestamp DateTime64(3, 'UTC'), -- This is a user defined timestamp, meant to be the /documents/ creation time
    inserted_at DateTime64(3, 'UTC'), -- When was this embedding inserted
    content String DEFAULT '', -- The actual text content that was embedded
    metadata String DEFAULT '{}', -- JSON metadata for the document, stored as a string
    embedding Array(Float64) -- The embedding itself
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64
, INDEX kafka_timestamp_minmax_sharded_posthog_document_embeddings_text_embedding_3_large_3072 _timestamp TYPE minmax GRANULARITY 3, CONSTRAINT embedding_dimension_check CHECK length(embedding) = 3072
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_posthog_document_embeddings_text_embedding_3_large_3072', '{replica}', inserted_at)

    PARTITION BY toMonday(timestamp)
    ORDER BY (team_id, toDate(timestamp), product, document_type, rendering, cityHash64(document_id))
    TTL timestamp + INTERVAL 3 MONTH
    SETTINGS index_granularity = 512, ttl_only_drop_parts = 1

ALTER TABLE sharded_posthog_document_embeddings_text_embedding_3_small_1536 ADD INDEX IF NOT EXISTS embedding_idx_l2 embedding TYPE vector_similarity('hnsw', 'L2Distance', 1536)

ALTER TABLE sharded_posthog_document_embeddings_text_embedding_3_small_1536 ADD INDEX IF NOT EXISTS embedding_idx_cosine embedding TYPE vector_similarity('hnsw', 'cosineDistance', 1536)

ALTER TABLE sharded_posthog_document_embeddings_text_embedding_3_large_3072 ADD INDEX IF NOT EXISTS embedding_idx_l2 embedding TYPE vector_similarity('hnsw', 'L2Distance', 3072)

ALTER TABLE sharded_posthog_document_embeddings_text_embedding_3_large_3072 ADD INDEX IF NOT EXISTS embedding_idx_cosine embedding TYPE vector_similarity('hnsw', 'cosineDistance', 3072)

CREATE TABLE IF NOT EXISTS distributed_posthog_document_embeddings_text_embedding_3_small_1536
(
    team_id Int64,
    product LowCardinality(String), -- Like "error tracking" or "session replay" - basically a bucket
    document_type LowCardinality(String), -- The type of document this is an embedding for
    rendering LowCardinality(String), -- How the document was rendered to text
    document_id String, -- A uuid, a path like "issue/<chunk_id>", whatever you like really
    timestamp DateTime64(3, 'UTC'), -- This is a user defined timestamp, meant to be the /documents/ creation time
    inserted_at DateTime64(3, 'UTC'), -- When was this embedding inserted
    content String DEFAULT '', -- The actual text content that was embedded
    metadata String DEFAULT '{}', -- JSON metadata for the document, stored as a string
    embedding Array(Float64) -- The embedding itself
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

) ENGINE = Distributed('posthog', 'default', 'sharded_posthog_document_embeddings_text_embedding_3_small_1536', cityHash64(document_id))

CREATE TABLE IF NOT EXISTS distributed_posthog_document_embeddings_text_embedding_3_large_3072
(
    team_id Int64,
    product LowCardinality(String), -- Like "error tracking" or "session replay" - basically a bucket
    document_type LowCardinality(String), -- The type of document this is an embedding for
    rendering LowCardinality(String), -- How the document was rendered to text
    document_id String, -- A uuid, a path like "issue/<chunk_id>", whatever you like really
    timestamp DateTime64(3, 'UTC'), -- This is a user defined timestamp, meant to be the /documents/ creation time
    inserted_at DateTime64(3, 'UTC'), -- When was this embedding inserted
    content String DEFAULT '', -- The actual text content that was embedded
    metadata String DEFAULT '{}', -- JSON metadata for the document, stored as a string
    embedding Array(Float64) -- The embedding itself
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

) ENGINE = Distributed('posthog', 'default', 'sharded_posthog_document_embeddings_text_embedding_3_large_3072', cityHash64(document_id))

CREATE TABLE IF NOT EXISTS writable_posthog_document_embeddings_text_embedding_3_small_1536
(
    team_id Int64,
    product LowCardinality(String), -- Like "error tracking" or "session replay" - basically a bucket
    document_type LowCardinality(String), -- The type of document this is an embedding for
    rendering LowCardinality(String), -- How the document was rendered to text
    document_id String, -- A uuid, a path like "issue/<chunk_id>", whatever you like really
    timestamp DateTime64(3, 'UTC'), -- This is a user defined timestamp, meant to be the /documents/ creation time
    inserted_at DateTime64(3, 'UTC'), -- When was this embedding inserted
    content String DEFAULT '', -- The actual text content that was embedded
    metadata String DEFAULT '{}', -- JSON metadata for the document, stored as a string
    embedding Array(Float64) -- The embedding itself
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

) ENGINE = Distributed('posthog', 'default', 'sharded_posthog_document_embeddings_text_embedding_3_small_1536', cityHash64(document_id))

CREATE TABLE IF NOT EXISTS writable_posthog_document_embeddings_text_embedding_3_large_3072
(
    team_id Int64,
    product LowCardinality(String), -- Like "error tracking" or "session replay" - basically a bucket
    document_type LowCardinality(String), -- The type of document this is an embedding for
    rendering LowCardinality(String), -- How the document was rendered to text
    document_id String, -- A uuid, a path like "issue/<chunk_id>", whatever you like really
    timestamp DateTime64(3, 'UTC'), -- This is a user defined timestamp, meant to be the /documents/ creation time
    inserted_at DateTime64(3, 'UTC'), -- When was this embedding inserted
    content String DEFAULT '', -- The actual text content that was embedded
    metadata String DEFAULT '{}', -- JSON metadata for the document, stored as a string
    embedding Array(Float64) -- The embedding itself
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

) ENGINE = Distributed('posthog', 'default', 'sharded_posthog_document_embeddings_text_embedding_3_large_3072', cityHash64(document_id))

CREATE MATERIALIZED VIEW IF NOT EXISTS posthog_document_embeddings_text_embedding_3_small_1536_mv
TO writable_posthog_document_embeddings_text_embedding_3_small_1536
AS SELECT
team_id,
product,
document_type,
rendering,
document_id,
timestamp,
inserted_at,
content,
metadata,
embedding,
_timestamp,
_offset,
_partition
FROM default.sharded_posthog_document_embeddings_buffer
WHERE model_name = 'text-embedding-3-small-1536'

CREATE MATERIALIZED VIEW IF NOT EXISTS posthog_document_embeddings_text_embedding_3_large_3072_mv
TO writable_posthog_document_embeddings_text_embedding_3_large_3072
AS SELECT
team_id,
product,
document_type,
rendering,
document_id,
timestamp,
inserted_at,
content,
metadata,
embedding,
_timestamp,
_offset,
_partition
FROM default.sharded_posthog_document_embeddings_buffer
WHERE model_name = 'text-embedding-3-large-3072'

CREATE VIEW IF NOT EXISTS posthog_document_embeddings_union_view
AS 
        SELECT
            team_id,
            product,
            document_type,
            rendering,
            document_id,
            timestamp,
            inserted_at,
            content,
            metadata,
            embedding,
            _timestamp,
            _offset,
            _partition,
            'text-embedding-3-small-1536' AS model_name
        FROM distributed_posthog_document_embeddings_text_embedding_3_small_1536 UNION ALL 
        SELECT
            team_id,
            product,
            document_type,
            rendering,
            document_id,
            timestamp,
            inserted_at,
            content,
            metadata,
            embedding,
            _timestamp,
            _offset,
            _partition,
            'text-embedding-3-large-3072' AS model_name
        FROM distributed_posthog_document_embeddings_text_embedding_3_large_3072
