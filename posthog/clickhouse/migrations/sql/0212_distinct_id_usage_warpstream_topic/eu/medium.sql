DROP VIEW IF EXISTS distinct_id_usage_mv

DROP TABLE IF EXISTS kafka_distinct_id_usage

CREATE TABLE IF NOT EXISTS kafka_distinct_id_usage
(
    team_id Int64,
    distinct_id VARCHAR,
    timestamp DateTime64(6, 'UTC')
) ENGINE = Kafka(warpstream_ingestion, kafka_topic_list = 'distinct_id_usage_events_json', kafka_group_name = 'clickhouse_distinct_id_usage', kafka_format = 'JSONEachRow')
SETTINGS kafka_skip_broken_messages = 100

CREATE MATERIALIZED VIEW IF NOT EXISTS distinct_id_usage_mv
TO writable_distinct_id_usage
AS SELECT
    team_id,
    distinct_id,
    toStartOfMinute(timestamp) AS minute,
    1 AS event_count
FROM kafka_distinct_id_usage
