CREATE TABLE IF NOT EXISTS writable_error_tracking_issue_fingerprint_embeddings
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
 -- Unused, I think, but the above has it, so
) ENGINE = Distributed('posthog_single_shard', 'default', 'error_tracking_issue_fingerprint_embeddings')

CREATE TABLE IF NOT EXISTS kafka_error_tracking_issue_fingerprint_embeddings
(
    team_id Int64,
    model_name LowCardinality(String),
    embedding_version Int64, -- This is the given iteration of the embedding approach - it will /probably/ always be 0, but we want to be able to iterate on e.g. what we feed the model, so we'll leave that door open for now
    fingerprint VARCHAR,
    inserted_at DateTime64(3, 'UTC'),
    embeddings Array(Float64) -- We could experiment with quantization, but if we do we can use a new column, for now we'll eat the inefficiency
     -- Unused, I think, but the above has it, so
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_error_tracking_issue_fingerprint_embeddings', kafka_group_name = 'clickhouse_error_tracking_fingerprint_embeddings', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS error_tracking_issue_fingerprint_embeddings_mv
TO writable_error_tracking_issue_fingerprint_embeddings
AS SELECT
team_id,
model_name,
embedding_version,
fingerprint,
_timestamp as inserted_at,
embeddings,
_timestamp,
_offset,
_partition
FROM default.kafka_error_tracking_issue_fingerprint_embeddings
