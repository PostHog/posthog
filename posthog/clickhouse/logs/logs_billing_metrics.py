from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

TABLE_NAME = "logs_billing_metrics"


def LOGS_BILLING_METRICS_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `bytes_uncompressed` SimpleAggregateFunction(sum, UInt64),
    `bytes_compressed` SimpleAggregateFunction(sum, UInt64),
    `record_count` SimpleAggregateFunction(sum, UInt64)
)
ENGINE = {AggregatingMergeTree(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toYYYYMM(time_bucket)
ORDER BY (team_id, time_bucket, service_name)
SETTINGS
    deduplicate_merge_projection_mode = 'rebuild',
    index_granularity = 8192
"""


def LOGS_BILLING_METRICS_DISTRIBUTED_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {database}.logs_billing_metrics_distributed AS {database}.{table_name} ENGINE = {engine}
""".format(
        engine=Distributed(
            data_table=TABLE_NAME,
            cluster=settings.CLICKHOUSE_LOGS_CLUSTER,
        ),
        database=settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE,
        table_name=TABLE_NAME,
    )
