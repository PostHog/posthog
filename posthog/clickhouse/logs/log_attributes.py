from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, ReplicationScheme

TABLE_NAME = "log_attributes"

STORAGE_POLICY = lambda: "hot" if settings.CLICKHOUSE_LOGS_ENABLE_STORAGE_POLICY else "default"


LOG_ATTRIBUTES_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
(
    `team_id` Int32 CODEC(DoubleDelta, ZSTD(1)),
    `time_bucket` DateTime64(0) CODEC(DoubleDelta, ZSTD(1)),
    `original_expiry_time_bucket` DateTime64(0) CODEC(DoubleDelta, ZSTD(1)),
    `service_name` LowCardinality(String) CODEC(ZSTD(1)),
    `resource_fingerprint` UInt64 DEFAULT 0 CODEC(DoubleDelta, ZSTD(1)),
    `attribute_key` LowCardinality(String) CODEC(ZSTD(1)),
    `attribute_value` String CODEC(ZSTD(1)),
    `attribute_count` SimpleAggregateFunction(sum, UInt64),
    `attribute_type` LowCardinality(String),
    INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1,
    INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
)
ENGINE = {AggregatingMergeTree("log_attributes", replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(original_expiry_time_bucket)
ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)
SETTINGS
    storage_policy = '{STORAGE_POLICY()}',
    deduplicate_merge_projection_mode = 'drop',
    index_granularity = 8192
"""
