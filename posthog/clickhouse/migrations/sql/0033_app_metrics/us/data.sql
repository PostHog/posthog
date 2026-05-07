CREATE TABLE IF NOT EXISTS sharded_app_metrics ON CLUSTER 'posthog'
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
ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_app_metrics', '{replica}')
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, plugin_config_id, job_id, category, toStartOfHour(timestamp), error_type, error_uuid)

CREATE TABLE IF NOT EXISTS app_metrics
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
ENGINE=Kafka(msk_cluster, kafka_topic_list = 'clickhouse_app_metrics', kafka_group_name = 'clickhouse_app_metrics', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS app_metrics_mv
TO sharded_app_metrics
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
