CREATE TABLE IF NOT EXISTS kafka_app_metrics2_ws
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    app_source LowCardinality(String),
    app_source_id String,
    instance_id String,
    metric_kind String,
    metric_name String,
    count Int64
)
ENGINE=Kafka(warpstream_ingestion, kafka_topic_list = 'clickhouse_app_metrics2', kafka_group_name = 'clickhouse_app_metrics2_ws', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS app_metrics2_ws_mv
TO writable_app_metrics2
AS SELECT
team_id,
timestamp,
app_source,
app_source_id,
instance_id,
metric_kind,
metric_name,
count,
_timestamp,
_offset,
_partition
FROM kafka_app_metrics2_ws

CREATE TABLE IF NOT EXISTS kafka_tophog_ws
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
) ENGINE = Kafka(warpstream_ingestion, kafka_topic_list = 'clickhouse_tophog', kafka_group_name = 'clickhouse_tophog_ws', kafka_format = 'JSONEachRow')
SETTINGS date_time_input_format = 'best_effort', kafka_skip_broken_messages = 100

CREATE MATERIALIZED VIEW IF NOT EXISTS tophog_ws_mv
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
FROM kafka_tophog_ws
