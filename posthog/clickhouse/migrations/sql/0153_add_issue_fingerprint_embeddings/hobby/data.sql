CREATE TABLE IF NOT EXISTS error_tracking_issue_fingerprint_embeddings
(
    team_id Int64,
    model_name LowCardinality(String),
    embedding_version Int64, -- This is the given iteration of the embedding approach - it will /probably/ always be 0, but we want to be able to iterate on e.g. what we feed the model, so we'll leave that door open for now
    fingerprint VARCHAR,
    inserted_at DateTime64(3, 'UTC'),
    embeddings Array(Float64) -- We could experiment with quantization, but if we do we can use a new column, for now we'll eat the inefficiency
    
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

    , INDEX kafka_timestamp_minmax_error_tracking_issue_fingerprint_embeddings _timestamp TYPE minmax GRANULARITY 3
     -- Unused, I think, but the above has it, so
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.error_tracking_issue_fingerprint_embeddings', '{replica}-{shard}', inserted_at)

    ORDER BY (team_id, model_name, embedding_version, fingerprint)
    SETTINGS index_granularity = 512
