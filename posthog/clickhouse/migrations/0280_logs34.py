from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import (
    KAFKA_LOGS34_AVRO_MV,
    KAFKA_LOGS_AVRO_BILLING_METRICS_MV,
    KAFKA_LOGS_AVRO_KAFKA_METRICS_MV,
    KAFKA_LOGS_AVRO_TABLE_SQL,
    LOGS34_DISTRIBUTED_TABLE_SQL,
    LOGS34_TABLE_SQL,
    LOGS_BILLING_METRICS_DISTRIBUTED_TABLE_SQL,
    LOGS_BILLING_METRICS_TABLE_SQL,
    LOGS_KAFKA_METRICS_DISTRIBUTED_TABLE_SQL,
    LOGS_KAFKA_METRICS_TABLE_SQL,
)
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

# 0309 dropped log_attributes2 and the two views that wrote to it, so the SQL
# they need is inlined here instead of in a shared definition module.

TABLE_NAME = "logs34"
LOG_ATTRIBUTES2_TABLE_NAME = "log_attributes2"


def LOG_ATTRIBUTES2_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{LOG_ATTRIBUTES2_TABLE_NAME}
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
ENGINE = {AggregatingMergeTree(LOG_ATTRIBUTES2_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
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
            data_table=LOG_ATTRIBUTES2_TABLE_NAME,
            cluster=settings.CLICKHOUSE_LOGS_CLUSTER,
        ),
        database=settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE,
        table_name=LOG_ATTRIBUTES2_TABLE_NAME,
    )


def LOGS34_TO_LOG_ATTRIBUTES_MV():
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}_to_log_attributes TO {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{LOG_ATTRIBUTES2_TABLE_NAME}
(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `original_expiry_time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `resource_fingerprint` UInt64,
    `attribute_key` LowCardinality(String),
    `attribute_value` String,
    `attribute_type` LowCardinality(String),
    `attribute_count` SimpleAggregateFunction(sum, UInt64)
)
AS SELECT
    team_id,
    time_bucket,
    original_expiry_time_bucket,
    service_name,
    resource_fingerprint,
    attribute_key,
    attribute_value,
    attribute_type,
    attribute_count
FROM
(
    SELECT
        team_id AS team_id,
        toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
        toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
        service_name AS service_name,
        resource_fingerprint,
        mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
        arrayJoin(attributes) AS attribute,
        'log' AS attribute_type,
        attribute.1 AS attribute_key,
        attribute.2 AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
    GROUP BY
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attributes
)
"""


def LOGS34_TO_RESOURCE_ATTRIBUTES_MV():
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}_to_resource_attributes TO {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{LOG_ATTRIBUTES2_TABLE_NAME}
(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `original_expiry_time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `resource_fingerprint` UInt64,
    `attribute_key` LowCardinality(String),
    `attribute_value` String,
    `attribute_type` LowCardinality(String),
    `attribute_count` SimpleAggregateFunction(sum, UInt64)
)
AS SELECT
    team_id,
    time_bucket,
    original_expiry_time_bucket,
    service_name,
    resource_fingerprint,
    attribute_key,
    attribute_value,
    attribute_type,
    attribute_count
FROM
(
    SELECT
        team_id AS team_id,
        toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
        toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
        service_name AS service_name,
        resource_fingerprint,
        arrayJoin(resource_attributes) AS attribute,
        'resource' AS attribute_type,
        attribute.1 AS attribute_key,
        attribute.2 AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
    GROUP BY
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        resource_attributes
)
"""


operations = [
    run_sql_with_exceptions(LOGS34_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOG_ATTRIBUTES2_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS_BILLING_METRICS_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS_KAFKA_METRICS_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS34_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOG_ATTRIBUTES2_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS_BILLING_METRICS_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS_KAFKA_METRICS_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS34_TO_LOG_ATTRIBUTES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS34_TO_RESOURCE_ATTRIBUTES_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_LOGS_AVRO_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_LOGS34_AVRO_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_LOGS_AVRO_KAFKA_METRICS_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(KAFKA_LOGS_AVRO_BILLING_METRICS_MV(), node_roles=[NodeRole.LOGS]),
]
