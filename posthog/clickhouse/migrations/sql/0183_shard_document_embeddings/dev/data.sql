CREATE TABLE IF NOT EXISTS partitioned_sharded_posthog_document_embeddings
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

    , INDEX kafka_timestamp_minmax_partitioned_sharded_posthog_document_embeddings _timestamp TYPE minmax GRANULARITY 3
    
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.partitioned_sharded_posthog_document_embeddings', '{replica}', inserted_at)

    -- This index assumes:
    --  - people will /always/ provide a date range
    --  - "show me documents of type X by any model" will be more common than "show me all documents by model X"
    --  - Documents with the same ID whose timestamp is in the same day are the same document, and the later inserted one should be retained
    PARTITION BY toMonday(timestamp)
    ORDER BY (team_id, toDate(timestamp), product, document_type, model_name, rendering, cityHash64(document_id))
    TTL timestamp + INTERVAL 3 MONTH
    SETTINGS index_granularity = 512, ttl_only_drop_parts = 1

CREATE TABLE IF NOT EXISTS distributed_posthog_document_embeddings
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
