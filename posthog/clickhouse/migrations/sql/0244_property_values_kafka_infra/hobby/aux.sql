CREATE TABLE IF NOT EXISTS property_values
(
    `team_id` Int64 CODEC(DoubleDelta, ZSTD(1)),
    `property_type` LowCardinality(String),
    `property_key` LowCardinality(String),
    `property_value` String,
    `property_count` SimpleAggregateFunction(sum, UInt64),
    `last_seen` SimpleAggregateFunction(max, DateTime) DEFAULT now()
    ,
    INDEX idx_property_value property_value TYPE text(tokenizer = ngrams(3), preprocessor = lower(property_value)) GRANULARITY 1
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.property_values', '{replica}-{shard}')

ORDER BY (team_id, property_type, property_key, property_value)
TTL last_seen + INTERVAL 30 DAY DELETE
SETTINGS
    index_granularity = 8192,
    enable_full_text_index = 1

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
