from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, MergeTreeEngine, ReplicationScheme

TABLE_NAME = "trace_attributes"
TABLE_NAME_V2 = "trace_attributes2"


def _trace_attributes_table_sql(table_name: str, engine: str):
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{table_name}
(
    `team_id` Int32,
    `original_expiry_time_bucket` DateTime64(0),
    `time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `resource_fingerprint` UInt64 DEFAULT 0,
    `attribute_key` LowCardinality(String),
    `attribute_value` String,
    `attribute_type` LowCardinality(String),
    `attribute_count` SimpleAggregateFunction(sum, UInt64),
    INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 4,
    INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 4,
    INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 4,
    INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 4
)
ENGINE = {engine}
PARTITION BY toDate(original_expiry_time_bucket)
ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)
TTL original_expiry_time_bucket
SETTINGS
    index_granularity = 8192
"""


def TRACE_ATTRIBUTES_TABLE_SQL():
    return _trace_attributes_table_sql(
        TABLE_NAME,
        str(MergeTreeEngine(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)),
    )


def TRACE_ATTRIBUTES2_TABLE_SQL():
    return _trace_attributes_table_sql(
        TABLE_NAME_V2,
        str(AggregatingMergeTree(TABLE_NAME_V2, replication_scheme=ReplicationScheme.REPLICATED)),
    )
