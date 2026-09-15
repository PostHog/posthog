from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

# Log pattern rollup for anomaly detection, at logs_volume_buckets' grain plus
# `pattern`, so a reader can ask how often one masked shape occurred in one
# series. The writer picks the bucket width, not this table. logs_volume_buckets
# uses a 5-minute UTC grid and the sizing here assumes the same.
#
# Like logs_volume_buckets, this table holds partial counts, so readers must
# always GROUP BY the key columns and sum(log_count), never read rows raw. See
# that table for the rest of the summing and dedup semantics, which are the
# same here.
#
# ORDER BY keeps logs_volume_buckets' time-early prefix, for the reason its own
# comment gives, and appends `pattern` last. Reading one shape's history is then
# a range scan inside one series.
#
# PRIMARY KEY stops before `pattern`. The sparse index keeps one mark per
# granule, so an unbounded String there stores a full copy per mark for a column
# too distinct to prune granules on. The grain does not change: ORDER BY still
# carries `pattern`, so merges still collapse on it.
#
# `pattern` is a plain String. Its cardinality is unbounded by construction, so
# a LowCardinality dictionary costs more than it saves. It carries no explicit
# codec either: the server compresses every column with ZSTD, and a column last
# in the sort key stores equal values adjacent, which ZSTD handles well.
#
# `severity_text` stays in the grain, so the same shape at two severities keeps
# two rows. A reader that ignores severity can still collapse them, but a reader
# that keeps it can tell an escalation from a new shape.
#
# `pattern_version` sits in the grain, just before `pattern`. Two patterns only
# mean the same shape when the masker version that produced them matches, so a
# masking change must start a new series rather than merge into the old one.
#
# TTL is 42 days (6 weekly samples per time-of-week slot), independent of raw
# log retention. Nothing caps patterns per series yet, so until something does,
# row count here is bounded only by how many distinct shapes a service emits.

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
    `pattern_version` UInt8,
    `pattern` String,
    `log_count` SimpleAggregateFunction(sum, UInt64)
)
ENGINE = {AggregatingMergeTree(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(time_bucket)
ORDER BY (team_id, time_bucket, service_name, namespace, environment, severity_text, pattern_version, pattern)
PRIMARY KEY (team_id, time_bucket, service_name, namespace, environment, severity_text, pattern_version)
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
