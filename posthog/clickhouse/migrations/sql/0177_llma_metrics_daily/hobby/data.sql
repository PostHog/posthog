CREATE TABLE IF NOT EXISTS llma_metrics_daily
(
    date Date,
    team_id UInt64,
    metric_name String,
    metric_value Float64
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.llma_metrics_daily', '{replica}-{shard}')
PARTITION BY toYYYYMM(date)
ORDER BY (team_id, date, metric_name)
