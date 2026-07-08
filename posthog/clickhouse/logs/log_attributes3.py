from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

TABLE_NAME = "log_attributes3"
DISTRIBUTED_TABLE_NAME = "log_attributes3_distributed"


def LOG_ATTRIBUTES3_TABLE_SQL():
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
    `severity_text` LowCardinality(String),
    INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1,
    INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
)
ENGINE = {AggregatingMergeTree(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(original_expiry_time_bucket)
ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value, severity_text)
TTL original_expiry_time_bucket
SETTINGS
    deduplicate_merge_projection_mode = 'drop',
    index_granularity = 8192
"""


def LOG_ATTRIBUTES3_DISTRIBUTED_TABLE_SQL():
    # A separate distributed table rather than repointing log_attributes_distributed:
    # log_attributes3 only holds data written since its MVs went live, so cutting the
    # shared read table over before that floor ages past the TTL would silently drop
    # history for existing readers. Readers that need severity opt in here; the shared
    # table can be cut over (and this one retired) once gen 3 covers full retention.
    return """
CREATE TABLE IF NOT EXISTS {database}.{distributed_table_name} AS {database}.{table_name} ENGINE = {engine}
""".format(
        engine=Distributed(
            data_table=TABLE_NAME,
            cluster=settings.CLICKHOUSE_LOGS_CLUSTER,
        ),
        database=settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE,
        distributed_table_name=DISTRIBUTED_TABLE_NAME,
        table_name=TABLE_NAME,
    )
