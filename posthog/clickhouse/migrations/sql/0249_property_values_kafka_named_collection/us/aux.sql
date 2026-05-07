DROP TABLE IF EXISTS property_values_mv

DROP TABLE IF EXISTS kafka_property_values

CREATE TABLE IF NOT EXISTS kafka_property_values
(
    `team_id` Int64,
    `property_type` LowCardinality(String),
    `property_key` String,
    `property_value` String
) ENGINE = Kafka(warpstream_ingestion, kafka_topic_list = 'clickhouse_property_values', kafka_group_name = 'clickhouse_property_values', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS property_values_mv
TO property_values
AS SELECT
    team_id,
    property_type,
    property_key,
    property_value,
    toUInt64(1) as property_count,
    coalesce(_timestamp, now()) as last_seen
FROM default.kafka_property_values
WHERE lengthUTF8(property_key) > 0
  AND lengthUTF8(property_key) <= 400  -- matches Django PropertyDefinition.name max_length
  AND lengthUTF8(property_value) > 0
  AND lengthUTF8(property_value) < 256
