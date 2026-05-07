CREATE TABLE IF NOT EXISTS sharded_tophog
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
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/posthog.tophog', '{replica}')

PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (pipeline, lane, metric, timestamp, key)
TTL toDate(timestamp) + INTERVAL 30 DAY
SETTINGS ttl_only_drop_parts = 1

CREATE TABLE IF NOT EXISTS tophog
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
