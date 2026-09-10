from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

TABLE_NAME = "log_attributes2"


def LOG_ATTRIBUTES2_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `resource_fingerprint` UInt64 DEFAULT 0,
    `attribute_key` LowCardinality(String),
    `attribute_value` String CODEC(ZSTD(5)),
    `attribute_count` SimpleAggregateFunction(sum, UInt64),
    `attribute_type` LowCardinality(String) DEFAULT 'log',
    `original_expiry_time_bucket` DateTime DEFAULT now(),
    INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1,
    INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
)
ENGINE = {AggregatingMergeTree(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(original_expiry_time_bucket)
ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)
TTL original_expiry_time_bucket
SETTINGS
    deduplicate_merge_projection_mode = 'drop',
    index_granularity = 8192
"""


def LOG_ATTRIBUTES2_DISTRIBUTED_TABLE_SQL():
    return """
CREATE OR REPLACE TABLE {database}.log_attributes_distributed AS {database}.{table_name} ENGINE = {engine}
""".format(
        engine=Distributed(
            data_table=TABLE_NAME,
            cluster=settings.CLICKHOUSE_LOGS_CLUSTER,
        ),
        database=settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE,
        table_name=TABLE_NAME,
    )
