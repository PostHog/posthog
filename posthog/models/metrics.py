from posthog.clickhouse.table_engines import MergeTreeEngine, ReplicationScheme


CREATE_METRICS_COUNTER_EVENTS_TABLE = f"""
CREATE TABLE IF NOT EXISTS metrics_counter_events (
    name String,
    labels Map(String, String),
    timestamp DateTime64(3, 'UTC'),
    increment Float64
) ENGINE = {MergeTreeEngine('metrics_counter_events', replication_scheme=ReplicationScheme.REPLICATED)}
ORDER BY (name, labels, timestamp)
PARTITION BY toYYYYMM(timestamp)
"""
