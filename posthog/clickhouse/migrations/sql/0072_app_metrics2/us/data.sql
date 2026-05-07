DROP TABLE IF EXISTS app_metrics2_mv ON CLUSTER 'posthog'

DROP TABLE IF EXISTS kafka_app_metrics2 ON CLUSTER 'posthog'

DROP TABLE IF EXISTS app_metrics2 ON CLUSTER 'posthog'

DROP TABLE IF EXISTS sharded_app_metrics2 ON CLUSTER 'posthog'

CREATE TABLE IF NOT EXISTS sharded_app_metrics2
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    -- The name of the service or product that generated the metrics.
    -- Examples: plugins, hog
    app_source LowCardinality(String),
    -- An id for the app source.
    -- Set app_source to avoid collision with ids from other app sources if the id generation is not safe.
    -- Examples: A plugin id, a hog application id
    app_source_id String,
    -- A secondary id e.g. for the instance of app_source that generated this metric.
    -- This may be ommitted if app_source is a singleton.
    -- Examples: A plugin config id, a hog application config id
    instance_id String,
    metric_kind LowCardinality(String),
    metric_name LowCardinality(String),
    count SimpleAggregateFunction(sum, Int64)
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_app_metrics2', '{replica}')
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, app_source, app_source_id, instance_id, toStartOfHour(timestamp), metric_kind, metric_name)
TTL toDate(timestamp) + INTERVAL 90 DAY

CREATE TABLE IF NOT EXISTS app_metrics2
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    -- The name of the service or product that generated the metrics.
    -- Examples: plugins, hog
    app_source LowCardinality(String),
    -- An id for the app source.
    -- Set app_source to avoid collision with ids from other app sources if the id generation is not safe.
    -- Examples: A plugin id, a hog application id
    app_source_id String,
    -- A secondary id e.g. for the instance of app_source that generated this metric.
    -- This may be ommitted if app_source is a singleton.
    -- Examples: A plugin config id, a hog application config id
    instance_id String,
    metric_kind LowCardinality(String),
    metric_name LowCardinality(String),
    count SimpleAggregateFunction(sum, Int64)
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE=Distributed('posthog', 'default', 'sharded_app_metrics2', rand())

CREATE TABLE IF NOT EXISTS kafka_app_metrics2
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
ENGINE=Kafka(msk_cluster, kafka_topic_list = 'clickhouse_app_metrics2', kafka_group_name = 'clickhouse_app_metrics2', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS app_metrics2_mv
TO sharded_app_metrics2
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
FROM kafka_app_metrics2
