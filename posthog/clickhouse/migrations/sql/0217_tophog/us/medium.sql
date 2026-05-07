CREATE TABLE IF NOT EXISTS writable_tophog
(
    timestamp DateTime64(6, 'UTC'),
    metric LowCardinality(String),
    type LowCardinality(String) DEFAULT 'sum',
    key Map(LowCardinality(String), String),
    value Float64,
    count UInt64 DEFAULT 0,
    pipeline LowCardinality(String),
    lane LowCardinality(String),
    labels Map(LowCardinality(String), String)
) ENGINE = Distributed('posthog', 'default', 'sharded_tophog', cityHash64(toString(key)))

CREATE TABLE IF NOT EXISTS kafka_tophog
(
    timestamp DateTime64(6, 'UTC'),
    metric LowCardinality(String),
    type LowCardinality(String),
    key Map(LowCardinality(String), String),
    value Float64,
    count UInt64,
    pipeline LowCardinality(String),
    lane LowCardinality(String),
    labels Map(LowCardinality(String), String)
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_tophog', kafka_group_name = 'clickhouse_tophog', kafka_format = 'JSONEachRow')
SETTINGS date_time_input_format = 'best_effort', kafka_skip_broken_messages = 100

CREATE MATERIALIZED VIEW IF NOT EXISTS tophog_mv
TO writable_tophog
AS SELECT
    timestamp,
    metric,
    type,
    key,
    value,
    count,
    pipeline,
    lane,
    labels
FROM kafka_tophog
