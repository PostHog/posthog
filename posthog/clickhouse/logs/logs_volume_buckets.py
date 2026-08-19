from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

# Per-5-minute log volume rollup for anomaly detection. One row per
# (team, bucket, series) where the series identity is (service_name, namespace,
# environment, severity_text). Evidence dimensions (service.version,
# instrumentation_scope, host/pod) are deliberately excluded: they multiply
# rows 5-30x and belong on the filed issue record, not the rollup.
#
# Fed by the logs34_to_volume_buckets materialized view, which counts each
# inserted block. Blocks arrive per insert, so the table holds partial counts
# until merges collapse rows with equal keys. Readers must therefore always
# aggregate: GROUP BY the key columns and sum(log_count), never read rows raw.
# The SimpleAggregateFunction(sum, ...) column type is what makes merges sum
# instead of keeping one arbitrary row, matching logs_billing_metrics.
#
# A Kafka block that is consumed twice after a commit failure inserts twice and
# the duplicate survives as inflated counts. logs_billing_metrics accepts the
# same exposure, and the anomaly detector tolerates small inflation better than
# a missed bucket.
#
# Buckets are fixed wall-clock windows on a 5-minute UTC grid, never sliding.
#
# ORDER BY is time-early (unlike logs34's dims-early tail): the dominant read is
# team + scattered bucket windows with no dim predicate, and with only ~288
# buckets/series/day a dims-early key makes every granule span the whole day.
#
# TTL is 42 days (6 weekly samples per time-of-week slot), decoupled from raw
# log retention and deliberately capped: longer dilutes the recent picture.

TABLE_NAME = "logs_volume_buckets"
DISTRIBUTED_TABLE_NAME = "logs_volume_buckets_distributed"


def LOGS_VOLUME_BUCKETS_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
(
    `team_id` Int32,
    `time_bucket` DateTime('UTC') CODEC(DoubleDelta, ZSTD(1)),
    `service_name` LowCardinality(String),
    `namespace` LowCardinality(String),
    `environment` LowCardinality(String),
    `severity_text` LowCardinality(String),
    `log_count` SimpleAggregateFunction(sum, UInt64)
)
ENGINE = {AggregatingMergeTree(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(time_bucket)
ORDER BY (team_id, time_bucket, service_name, namespace, environment, severity_text)
TTL time_bucket + INTERVAL 42 DAY
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1
"""


def LOGS_VOLUME_BUCKETS_DISTRIBUTED_TABLE_SQL():
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
