CREATE TABLE IF NOT EXISTS error_tracking_issue_fingerprint_overrides ON CLUSTER 'posthog'
(
    team_id Int64,
    fingerprint VARCHAR,
    issue_id UUID,
    is_deleted Int8,
    version Int64
    
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

    , INDEX kafka_timestamp_minmax_error_tracking_issue_fingerprint_overrides _timestamp TYPE minmax GRANULARITY 3
    
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.error_tracking_issue_fingerprint_overrides', '{replica}-{shard}', version)

    ORDER BY (team_id, fingerprint)
    SETTINGS index_granularity = 512

CREATE TABLE IF NOT EXISTS kafka_error_tracking_issue_fingerprint_overrides ON CLUSTER 'posthog'
(
    team_id Int64,
    fingerprint VARCHAR,
    issue_id UUID,
    is_deleted Int8,
    version Int64
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_error_tracking_issue_fingerprint', kafka_group_name = 'clickhouse-error-tracking-issue-fingerprint-overrides', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS error_tracking_issue_fingerprint_overrides_mv ON CLUSTER 'posthog'
TO error_tracking_issue_fingerprint_overrides
AS SELECT
team_id,
fingerprint,
issue_id,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM default.kafka_error_tracking_issue_fingerprint_overrides
WHERE version > 0 -- only store updated rows, not newly inserted ones
