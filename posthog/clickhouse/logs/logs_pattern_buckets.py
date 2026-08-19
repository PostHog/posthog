from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

# Warn/error log counts per template on a 5-minute UTC bucket grid, for
# new-pattern anomaly detection. template_hash is a content-derived 64-bit
# hash of the masked log body; the table has no knowledge of the hash
# function. sample_body keeps one readable masked template per series so
# patterns can be shown without touching raw logs.
#
# The key is deliberately the logs_volume_buckets key plus template_hash:
# (service_name, namespace, environment) is the real service identity, and
# matching dims keep the evidence join between the two tables clean. The
# reader contract (partial rows, always GROUP BY and sum) and the 42-day TTL
# rationale are the same as logs_volume_buckets; see its header comment.

TABLE_NAME = "logs_pattern_buckets"


def LOGS_PATTERN_BUCKETS_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
(
    `team_id` Int32,
    `time_bucket` DateTime('UTC') CODEC(DoubleDelta, ZSTD(1)),
    `service_name` LowCardinality(String),
    `namespace` LowCardinality(String),
    `environment` LowCardinality(String),
    `severity_text` LowCardinality(String),
    `template_hash` UInt64,
    `sample_body` SimpleAggregateFunction(anyLast, String),
    `log_count` SimpleAggregateFunction(sum, UInt64)
)
ENGINE = {AggregatingMergeTree(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(time_bucket)
ORDER BY (team_id, time_bucket, service_name, namespace, environment, severity_text, template_hash)
TTL time_bucket + INTERVAL 42 DAY
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1
"""


def LOGS_PATTERN_BUCKETS_DISTRIBUTED_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {database}.logs_pattern_buckets_distributed AS {database}.{table_name} ENGINE = {engine}
""".format(
        engine=Distributed(
            data_table=TABLE_NAME,
            cluster=settings.CLICKHOUSE_LOGS_CLUSTER,
        ),
        database=settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE,
        table_name=TABLE_NAME,
    )
