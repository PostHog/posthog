from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

# Log volume rollup on a 5-minute UTC bucket grid, for anomaly detection.
# Higher-cardinality evidence dimensions (service.version, instrumentation
# scope, host/pod) are deliberately excluded to keep the series count low;
# they belong on the detection output, not the rollup.
#
# The table holds partial counts: every insert lands as its own rows and only
# merges collapse equal keys by summing, so readers must always GROUP BY the
# key columns and sum(log_count), never read rows raw. There is no dedup: a
# writer that inserts the same block twice (for example a replayed Kafka
# batch) inflates the count, which is accepted because small inflation beats
# a missed bucket.
#
# ORDER BY is time-early (unlike logs34's dims-early tail) because the dominant
# read is one team over a bucket window with no dim predicate, and rows per
# series per day are few enough that a dims-early key would make every granule
# span the whole day.
#
# TTL is 42 days (6 weekly samples per time-of-week slot) or the team's log
# retention, whichever is longer, so a team that keeps raw logs for longer than
# the baseline window keeps the rollup alongside them. `retention_days` carries
# the per-row retention the ingest path applied, which is why it sits in the
# key: a team that changes retention gets new series rather than rows whose TTL
# depends on merge order. With ttl_only_drop_parts a part waits for its longest
# lived row, so mixed retentions round up, never down.

TABLE_NAME = "logs_volume_buckets"


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
    `retention_days` UInt16,
    `log_count` SimpleAggregateFunction(sum, UInt64)
)
ENGINE = {AggregatingMergeTree(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(time_bucket)
PRIMARY KEY (team_id, time_bucket, service_name, namespace, environment, severity_text)
ORDER BY (team_id, time_bucket, service_name, namespace, environment, severity_text, retention_days)
TTL time_bucket + toIntervalDay(greatest(42, retention_days))
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1
"""


def LOGS_VOLUME_BUCKETS_DISTRIBUTED_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {database}.logs_volume_buckets_distributed AS {database}.{table_name} ENGINE = {engine}
""".format(
        engine=Distributed(
            data_table=TABLE_NAME,
            cluster=settings.CLICKHOUSE_LOGS_CLUSTER,
        ),
        database=settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE,
        table_name=TABLE_NAME,
    )
