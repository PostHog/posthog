CREATE TABLE IF NOT EXISTS writable_distinct_id_usage
(
    team_id Int64,
    distinct_id String,
    minute DateTime,
    event_count UInt64
) ENGINE = Distributed('posthog', 'default', 'sharded_distinct_id_usage', sipHash64(distinct_id))

CREATE TABLE IF NOT EXISTS kafka_distinct_id_usage
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC')
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_events_json', kafka_group_name = 'clickhouse_distinct_id_usage', kafka_format = 'JSONEachRow')
SETTINGS kafka_skip_broken_messages = 100

CREATE MATERIALIZED VIEW IF NOT EXISTS distinct_id_usage_mv
TO writable_distinct_id_usage
AS SELECT
    team_id,
    distinct_id,
    toStartOfMinute(timestamp) AS minute,
    1 AS event_count
FROM kafka_distinct_id_usage
