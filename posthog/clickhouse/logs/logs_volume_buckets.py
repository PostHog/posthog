from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme

# Per-5-minute log volume rollup for anomaly detection. One row per
# (team, bucket, generation, series) where the series identity is
# (service_name, namespace, environment, severity_text) — evidence dimensions
# (service.version, instrumentation_scope, host/pod) are deliberately excluded:
# they multiply rows 5-30x and belong on the filed issue record, not the rollup.
#
# Buckets are fixed wall-clock windows on a 5-minute UTC grid, never sliding.
# `generation` is the unix-millis start of one insert attempt, allocated and
# committed in Postgres (LogsVolumeBucketCompletion); storage here is immutable
# append-only and readers must filter to committed (time_bucket, generation)
# pairs — visibility is protocol-level, which is why this is a plain MergeTree
# rather than a Replacing/Collapsing variant (those can't express keys that
# vanish in a later generation, or double-count across generations).
#
# ORDER BY is time-early (unlike logs34's dims-early tail): the dominant read is
# team + scattered bucket windows with no dim predicate, and with only ~288
# buckets/series/day a dims-early key makes every granule span the whole day.
#
# TTL is 42 days (6 weekly samples per time-of-week slot), decoupled from raw
# log retention and deliberately capped: longer dilutes the recent picture.
# Superseded and never-committed generations are not deleted — invisible to
# readers, they age out with the TTL (~3x row overhead, sub-GB). The writer
# issues no mutations; explicit cleanup DELETEs stay a deferred option.

TABLE_NAME = "logs_volume_buckets"
DISTRIBUTED_TABLE_NAME = "logs_volume_buckets_distributed"


def LOGS_VOLUME_BUCKETS_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
(
    `team_id` Int32,
    `time_bucket` DateTime('UTC') CODEC(DoubleDelta, ZSTD(1)),
    `generation` UInt64,
    `service_name` LowCardinality(String),
    `namespace` LowCardinality(String),
    `environment` LowCardinality(String),
    `severity_text` LowCardinality(String),
    `log_count` UInt64
)
ENGINE = {MergeTreeEngine(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(time_bucket)
ORDER BY (team_id, time_bucket, generation, service_name, namespace, environment, severity_text)
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
