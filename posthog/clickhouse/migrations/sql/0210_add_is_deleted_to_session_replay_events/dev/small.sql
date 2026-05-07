DROP TABLE IF EXISTS session_replay_events_mv

DROP TABLE IF EXISTS kafka_session_replay_events

ALTER TABLE writable_session_replay_events
        ADD COLUMN IF NOT EXISTS is_deleted SimpleAggregateFunction(max, UInt8) DEFAULT 0

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
