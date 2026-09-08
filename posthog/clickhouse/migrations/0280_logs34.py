from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import (
    KAFKA_LOGS34_AVRO_MV,
    KAFKA_LOGS_AVRO_BILLING_METRICS_MV,
    KAFKA_LOGS_AVRO_KAFKA_METRICS_MV,
    KAFKA_LOGS_AVRO_TABLE_SQL,
    LOG_ATTRIBUTES2_DISTRIBUTED_TABLE_SQL,
    LOG_ATTRIBUTES2_TABLE_SQL,
    LOGS34_DISTRIBUTED_TABLE_SQL,
    LOGS34_TABLE_SQL,
    LOGS_BILLING_METRICS_DISTRIBUTED_TABLE_SQL,
    LOGS_BILLING_METRICS_TABLE_SQL,
    LOGS_KAFKA_METRICS_DISTRIBUTED_TABLE_SQL,
    LOGS_KAFKA_METRICS_TABLE_SQL,
)

# These views no longer exist outside this file, so their SQL has to stay
# local. Migration discovery imports every migration, so an import of a deleted
# definition stops every run.

TABLE_NAME = "logs34"
LOG_ATTRIBUTES_TABLE_NAME = "log_attributes2"


def LOGS34_TO_LOG_ATTRIBUTES_MV():
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}_to_log_attributes TO {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{LOG_ATTRIBUTES_TABLE_NAME}
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
CREATE MATERIALIZED VIEW IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}_to_resource_attributes TO {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{LOG_ATTRIBUTES_TABLE_NAME}
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
