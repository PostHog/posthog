CREATE TABLE IF NOT EXISTS kafka_app_metrics
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    plugin_config_id Int64,
    category LowCardinality(String),
    job_id String,
    successes Int64,
    successes_on_retry Int64,
    failures Int64,
    error_uuid UUID,
    error_type String,
    error_details String CODEC(ZSTD(3))
)
ENGINE=Kafka(msk_cluster, kafka_topic_list = 'clickhouse_app_metrics', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE TABLE IF NOT EXISTS writable_app_metrics
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    plugin_config_id Int64,
    category LowCardinality(String),
    job_id String,
    successes SimpleAggregateFunction(sum, Int64),
    successes_on_retry SimpleAggregateFunction(sum, Int64),
    failures SimpleAggregateFunction(sum, Int64),
    error_uuid UUID,
    error_type String,
    error_details String CODEC(ZSTD(3))
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE=Distributed('posthog', 'default', 'sharded_app_metrics', rand())

CREATE MATERIALIZED VIEW IF NOT EXISTS app_metrics_mv
TO writable_app_metrics
AS SELECT
team_id,
timestamp,
plugin_config_id,
category,
job_id,
successes,
successes_on_retry,
failures,
error_uuid,
error_type,
error_details,
_timestamp,
_offset,
_partition
FROM kafka_app_metrics

CREATE TABLE IF NOT EXISTS kafka_session_replay_events 
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    first_timestamp DateTime64(6, 'UTC'),
    last_timestamp DateTime64(6, 'UTC'),
    block_url Nullable(String),
    first_url Nullable(VARCHAR),
    urls Array(String),
    click_count Int64,
    keypress_count Int64,
    mouse_activity_count Int64,
    active_milliseconds Int64,
    console_log_count Int64,
    console_warn_count Int64,
    console_error_count Int64,
    size Int64,
    event_count Int64,
    message_count Int64,
    snapshot_source LowCardinality(Nullable(String)),
    snapshot_library Nullable(String),
    retention_period_days Nullable(Int64),
    is_deleted UInt8,
    ai_tags_fixed Array(String),
    ai_tags_freeform Array(String),
    ai_highlighted UInt8,
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_session_replay_events', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE TABLE IF NOT EXISTS writable_session_replay_events 
(
    -- part of order by so will aggregate correctly
    session_id VARCHAR,
    -- part of order by so will aggregate correctly
    team_id Int64,
    -- ClickHouse will pick any value of distinct_id for the session
    -- this is fine since even if the distinct_id changes during a session
    -- it will still (or should still) map to the same person
    distinct_id VARCHAR,
    min_first_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_last_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    -- session recording v2 blocks
    block_first_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
    block_last_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
    block_urls SimpleAggregateFunction(groupArrayArray, Array(String)),
    -- store the first url of the session so we can quickly show that in playlists
    first_url AggregateFunction(argMin, Nullable(VARCHAR), DateTime64(6, 'UTC')),
    -- but also store each url so we can query by visited page without having to scan all events
    -- despite the name we can put mobile screens in here as well to give same functionality across platforms
    all_urls SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    click_count SimpleAggregateFunction(sum, Int64),
    keypress_count SimpleAggregateFunction(sum, Int64),
    mouse_activity_count SimpleAggregateFunction(sum, Int64),
    active_milliseconds SimpleAggregateFunction(sum, Int64),
    console_log_count SimpleAggregateFunction(sum, Int64),
    console_warn_count SimpleAggregateFunction(sum, Int64),
    console_error_count SimpleAggregateFunction(sum, Int64),
    -- this column allows us to estimate the amount of data that is being ingested
    size SimpleAggregateFunction(sum, Int64),
    -- this allows us to count the number of messages received in a session
    -- often very useful in incidents or debugging
    message_count SimpleAggregateFunction(sum, Int64),
    -- this allows us to count the number of snapshot events received in a session
    -- often very useful in incidents or debugging
    -- because we batch events we expect message_count to be lower than event_count
    event_count SimpleAggregateFunction(sum, Int64),
    -- which source the snapshots came from Mobile or Web. Web if absent
    snapshot_source AggregateFunction(argMin, LowCardinality(Nullable(String)), DateTime64(6, 'UTC')),
    -- knowing something is mobile isn't enough, we need to know if e.g. RN or flutter
    snapshot_library AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    _timestamp SimpleAggregateFunction(max, DateTime),
    -- retention period for this session, in days. Useful to show TTL for the recording
    retention_period_days SimpleAggregateFunction(max, Nullable(Int64)),
    -- marks the recording as deleted for crypto shredding; once 1, merges keep it as 1
    is_deleted SimpleAggregateFunction(max, UInt8) DEFAULT 0,
    -- AI-generated session tags from the summarization pipeline (fixed taxonomy)
    ai_tags_fixed SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    -- AI-generated session tags from the summarization pipeline (free-form)
    ai_tags_freeform SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
    -- AI-generated flag indicating the session is highlighted / worth watching
    ai_highlighted SimpleAggregateFunction(max, UInt8) DEFAULT 0,
) ENGINE = Distributed('posthog', 'default', 'sharded_session_replay_events', sipHash64(distinct_id))

CREATE MATERIALIZED VIEW IF NOT EXISTS session_replay_events_mv 
TO default.writable_session_replay_events (
`session_id` String, `team_id` Int64, `distinct_id` String,
`min_first_timestamp` DateTime64(6, 'UTC'),
`max_last_timestamp` DateTime64(6, 'UTC'),
`block_first_timestamps` SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
`block_last_timestamps` SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
`block_urls` SimpleAggregateFunction(groupArrayArray, Array(String)),
`first_url` AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
`all_urls` SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
`click_count` Int64, `keypress_count` Int64,
`mouse_activity_count` Int64, `active_milliseconds` Int64,
`console_log_count` Int64, `console_warn_count` Int64,
`console_error_count` Int64, `size` Int64, `message_count` Int64,
`event_count` Int64,
`snapshot_source` AggregateFunction(argMin, LowCardinality(Nullable(String)), DateTime64(6, 'UTC')),
`snapshot_library` AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
`_timestamp` Nullable(DateTime)
,`retention_period_days` SimpleAggregateFunction(max, Nullable(Int64))
,`is_deleted` SimpleAggregateFunction(max, UInt8)
,`ai_tags_fixed` SimpleAggregateFunction(groupUniqArrayArray, Array(String))
,`ai_tags_freeform` SimpleAggregateFunction(groupUniqArrayArray, Array(String))
,`ai_highlighted` SimpleAggregateFunction(max, UInt8)
)
AS SELECT
session_id,
team_id,
any(distinct_id) as distinct_id,
min(first_timestamp) AS min_first_timestamp,
max(last_timestamp) AS max_last_timestamp,
groupArray(if(block_url != '', first_timestamp, NULL)) AS block_first_timestamps,
groupArray(if(block_url != '', last_timestamp, NULL)) AS block_last_timestamps,
groupArray(block_url) AS block_urls,
-- TRICKY: ClickHouse will pick a relatively random first_url
-- when it collapses the aggregating merge tree
-- unless we teach it what we want...
-- argMin ignores null values
-- so this will get the first non-null value of first_url
-- for each group of session_id and team_id
-- by min of first_timestamp in the batch
-- this is an aggregate function, not a simple aggregate function
-- so we have to write to argMinState, and query with argMinMerge
argMinState(first_url, first_timestamp) as first_url,
groupUniqArrayArray(urls) as all_urls,
sum(click_count) as click_count,
sum(keypress_count) as keypress_count,
sum(mouse_activity_count) as mouse_activity_count,
sum(active_milliseconds) as active_milliseconds,
sum(console_log_count) as console_log_count,
sum(console_warn_count) as console_warn_count,
sum(console_error_count) as console_error_count,
sum(size) as size,
-- we can count the number of kafka messages instead of sending it explicitly
sum(message_count) as message_count,
sum(event_count) as event_count,
argMinState(snapshot_source, first_timestamp) as snapshot_source,
argMinState(snapshot_library, first_timestamp) as snapshot_library,
max(_timestamp) as _timestamp
,max(retention_period_days) as retention_period_days
,max(is_deleted) as is_deleted
,groupUniqArrayArray(ai_tags_fixed) as ai_tags_fixed
,groupUniqArrayArray(ai_tags_freeform) as ai_tags_freeform
,max(ai_highlighted) as ai_highlighted
FROM default.kafka_session_replay_events
group by session_id, team_id

CREATE TABLE IF NOT EXISTS writable_log_entries 
(
    team_id UInt64,
    -- The name of the service or product that generated the logs.
    -- Examples: batch_exports
    log_source LowCardinality(String),
    -- An id for the log source.
    -- Set log_source to avoid collision with ids from other log sources if the id generation is not safe.
    -- Examples: A batch export id, a cronjob id, a plugin id.
    log_source_id String,
    -- A secondary id e.g. for the instance of log_source that generated this log.
    -- This may be ommitted if log_source is a singleton.
    -- Examples: A batch export run id, a plugin_config id, a thread id, a process id, a machine id.
    instance_id String,
    -- Timestamp indicating when the log was generated.
    timestamp DateTime64(6, 'UTC'),
    -- The log level.
    -- Examples: INFO, WARNING, DEBUG, ERROR.
    level LowCardinality(String),
    -- The actual log message.
    message String
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = Distributed('posthog', 'default', 'sharded_log_entries', rand())

CREATE TABLE IF NOT EXISTS kafka_log_entries_v3 
(
    team_id UInt64,
    -- The name of the service or product that generated the logs.
    -- Examples: batch_exports
    log_source LowCardinality(String),
    -- An id for the log source.
    -- Set log_source to avoid collision with ids from other log sources if the id generation is not safe.
    -- Examples: A batch export id, a cronjob id, a plugin id.
    log_source_id String,
    -- A secondary id e.g. for the instance of log_source that generated this log.
    -- This may be ommitted if log_source is a singleton.
    -- Examples: A batch export run id, a plugin_config id, a thread id, a process id, a machine id.
    instance_id String,
    -- Timestamp indicating when the log was generated.
    timestamp DateTime64(6, 'UTC'),
    -- The log level.
    -- Examples: INFO, WARNING, DEBUG, ERROR.
    level LowCardinality(String),
    -- The actual log message.
    message String
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'log_entries', kafka_group_name = 'clickhouse_log_entries', kafka_format = 'JSONEachRow')

    SETTINGS kafka_skip_broken_messages = 100

CREATE MATERIALIZED VIEW IF NOT EXISTS log_entries_v3_mv
    TO default.writable_log_entries
    AS SELECT
    team_id,
    log_source,
    log_source_id,
    instance_id,
    timestamp,
    level,
    message,
    _timestamp,
    _offset
    FROM default.kafka_log_entries_v3
    WHERE toDate(timestamp) <= today()

CREATE TABLE IF NOT EXISTS writable_ingestion_warnings
(
    team_id Int64,
    source LowCardinality(VARCHAR),
    type VARCHAR,
    details VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC')
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

) ENGINE = Distributed('posthog', 'default', 'sharded_ingestion_warnings', rand())

CREATE TABLE IF NOT EXISTS kafka_ingestion_warnings
(
    team_id Int64,
    source LowCardinality(VARCHAR),
    type VARCHAR,
    details VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC')
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_ingestion_warnings', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS ingestion_warnings_mv
TO default.writable_ingestion_warnings
AS SELECT
team_id,
source,
type,
details,
timestamp,
_timestamp,
_offset,
_partition
FROM default.kafka_ingestion_warnings

CREATE TABLE IF NOT EXISTS writable_events_dead_letter_queue 
(
    id UUID,
    event_uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    distinct_id VARCHAR,
    team_id Int64,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC'),
    ip VARCHAR,
    site_url VARCHAR,
    now DateTime64(6, 'UTC'),
    raw_payload VARCHAR,
    error_timestamp DateTime64(6, 'UTC'),
    error_location VARCHAR,
    error VARCHAR,
    tags Array(VARCHAR)
    
    
, _timestamp DateTime
, _offset UInt64

    
) ENGINE = Distributed('posthog_single_shard', 'default', 'events_dead_letter_queue')

CREATE TABLE IF NOT EXISTS kafka_events_dead_letter_queue 
(
    id UUID,
    event_uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    distinct_id VARCHAR,
    team_id Int64,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC'),
    ip VARCHAR,
    site_url VARCHAR,
    now DateTime64(6, 'UTC'),
    raw_payload VARCHAR,
    error_timestamp DateTime64(6, 'UTC'),
    error_location VARCHAR,
    error VARCHAR,
    tags Array(VARCHAR)
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'events_dead_letter_queue', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')
 SETTINGS kafka_skip_broken_messages=1000

CREATE MATERIALIZED VIEW IF NOT EXISTS events_dead_letter_queue_mv 
TO default.writable_events_dead_letter_queue
AS SELECT
id,
event_uuid,
event,
properties,
distinct_id,
team_id,
elements_chain,
created_at,
ip,
site_url,
now,
raw_payload,
error_timestamp,
error_location,
error,
tags,
_timestamp,
_offset
FROM default.kafka_events_dead_letter_queue

CREATE TABLE IF NOT EXISTS writable_error_tracking_issue_fingerprint_overrides 
(
    team_id Int64,
    fingerprint VARCHAR,
    issue_id UUID,
    is_deleted Int8,
    version Int64
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

) ENGINE = Distributed('posthog_single_shard', 'default', 'error_tracking_issue_fingerprint_overrides')

CREATE TABLE IF NOT EXISTS kafka_error_tracking_issue_fingerprint_overrides 
(
    team_id Int64,
    fingerprint VARCHAR,
    issue_id UUID,
    is_deleted Int8,
    version Int64
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_error_tracking_issue_fingerprint', kafka_group_name = 'clickhouse-error-tracking-issue-fingerprint-overrides', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS error_tracking_issue_fingerprint_overrides_mv 
TO writable_error_tracking_issue_fingerprint_overrides
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
