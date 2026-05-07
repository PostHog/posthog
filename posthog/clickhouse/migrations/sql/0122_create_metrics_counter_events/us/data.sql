CREATE TABLE IF NOT EXISTS custom_metrics_counter_events (
    name String,
    timestamp DateTime64(3, 'UTC') DEFAULT now(),
    labels Map(String, String),
    increment Float64
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.metrics_counter_events', '{replica}-{shard}')
ORDER BY (name, timestamp)
PARTITION BY toYYYYMM(timestamp)

CREATE OR REPLACE VIEW custom_metrics_counters AS
SELECT
    name,
    mapSort(labels) as labels,
    sum(increment) as value,
    '' as help,
    'counter' as type
FROM custom_metrics_counter_events
GROUP BY name, type, labels
ORDER BY name, type, labels

CREATE OR REPLACE VIEW custom_metrics(
         name String,
         labels Map(String, String),
         value Float64,
         help String,
         type String
    )
    AS SELECT * REPLACE (toFloat64(value) as value)
    FROM custom_metrics_test
    UNION ALL
    SELECT * REPLACE (toFloat64(value) as value)
    FROM custom_metrics_replication_queue
    UNION ALL
    SELECT * REPLACE (toFloat64(value) as value)
    FROM custom_metrics_events_recent_lag
    UNION ALL SELECT * FROM custom_metrics_counters
