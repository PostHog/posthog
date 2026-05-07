CREATE TABLE IF NOT EXISTS default.logs_kafka_metrics
(
    `_partition` UInt32,
    `_topic` String,
    `max_offset` SimpleAggregateFunction(max, UInt64),
    `max_observed_timestamp` SimpleAggregateFunction(max, DateTime64(9)),
    `max_timestamp` SimpleAggregateFunction(max, DateTime64(9)),
    `max_created_at` SimpleAggregateFunction(max, DateTime64(9)),
    `max_lag` SimpleAggregateFunction(max, UInt64)
)
ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.logs_kafka_metrics', '{replica}-{shard}')
ORDER BY (_topic, _partition)

CREATE TABLE IF NOT EXISTS default.logs_distributed AS default.logs32 ENGINE = Distributed('posthog_single_shard', 'default', 'logs32')

CREATE TABLE IF NOT EXISTS default.log_attributes_distributed AS default.log_attributes ENGINE = Distributed('posthog_single_shard', 'default', 'log_attributes')

CREATE TABLE IF NOT EXISTS default.logs_kafka_metrics_distributed AS default.logs_kafka_metrics ENGINE = Distributed('posthog_single_shard', 'default', 'logs_kafka_metrics')
