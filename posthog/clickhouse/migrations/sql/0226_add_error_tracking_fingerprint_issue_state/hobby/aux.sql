CREATE TABLE IF NOT EXISTS raw_error_tracking_fingerprint_issue_state 
(
    team_id Int64,
    fingerprint VARCHAR,
    issue_id UUID,
    issue_name Nullable(VARCHAR),
    issue_description Nullable(VARCHAR),
    issue_status VARCHAR,
    assigned_user_id Nullable(Int64),
    assigned_role_id Nullable(UUID),
    first_seen DateTime64(3, 'UTC'),
    is_deleted Int8,
    version Int64
    
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

    , INDEX kafka_timestamp_minmax_raw_error_tracking_fingerprint_issue_state _timestamp TYPE minmax GRANULARITY 3
    
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.raw_error_tracking_fingerprint_issue_state', '{replica}-{shard}', version)

    ORDER BY (team_id, fingerprint)
    SETTINGS index_granularity = 512

CREATE TABLE IF NOT EXISTS writable_error_tracking_fingerprint_issue_state 
(
    team_id Int64,
    fingerprint VARCHAR,
    issue_id UUID,
    issue_name Nullable(VARCHAR),
    issue_description Nullable(VARCHAR),
    issue_status VARCHAR,
    assigned_user_id Nullable(Int64),
    assigned_role_id Nullable(UUID),
    first_seen DateTime64(3, 'UTC'),
    is_deleted Int8,
    version Int64
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

) ENGINE = Distributed('aux', 'default', 'raw_error_tracking_fingerprint_issue_state')

CREATE TABLE IF NOT EXISTS kafka_error_tracking_fingerprint_issue_state 
(
    team_id Int64,
    fingerprint VARCHAR,
    issue_id UUID,
    issue_name Nullable(VARCHAR),
    issue_description Nullable(VARCHAR),
    issue_status VARCHAR,
    assigned_user_id Nullable(Int64),
    assigned_role_id Nullable(UUID),
    first_seen DateTime64(3, 'UTC'),
    is_deleted Int8,
    version Int64
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_error_tracking_fingerprint_issue_state', kafka_group_name = 'clickhouse-error-tracking-fingerprint-issue-state', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS error_tracking_fingerprint_issue_state_mv 
TO writable_error_tracking_fingerprint_issue_state
AS SELECT
team_id,
fingerprint,
issue_id,
issue_name,
issue_description,
issue_status,
assigned_user_id,
assigned_role_id,
first_seen,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM default.kafka_error_tracking_fingerprint_issue_state
