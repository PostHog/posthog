from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_FLAG_EVALUATIONS,
    KAFKA_COLUMNS_WITH_PARTITION,
    kafka_engine,
    ttl_period,
)
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_FLAG_EVALUATIONS

# Flag evaluation telemetry ($feature_flag_called events routed out of the events
# table). One row per evaluation, personless, fixed schema, 90-day retention.
#
# Naming convention follows the sharded main-cluster table family (see heatmaps):
#   * `sharded_flag_evaluations` — sharded replicated MergeTree on DATA nodes.
#   * `writable_flag_evaluations` — Distributed write path on the ingestion layer,
#     fans rows out to shards by the distinct_id hash.
#   * `flag_evaluations` — Distributed read path on DATA nodes. This is the name
#     HogQL will expose as `posthog.flag_evaluations`.
#   * `kafka_flag_evaluations` — Kafka engine table on the ingestion layer.
#   * `flag_evaluations_mv` — MV on the ingestion layer, kafka → writable.
FLAG_EVALUATIONS_TABLE = "flag_evaluations"
FLAG_EVALUATIONS_DATA_TABLE = f"sharded_{FLAG_EVALUATIONS_TABLE}"
FLAG_EVALUATIONS_WRITABLE_TABLE = f"writable_{FLAG_EVALUATIONS_TABLE}"
KAFKA_FLAG_EVALUATIONS_TABLE = f"kafka_{FLAG_EVALUATIONS_TABLE}"
FLAG_EVALUATIONS_MV_TABLE = f"{FLAG_EVALUATIONS_TABLE}_mv"

FLAG_EVALUATIONS_TTL_DAYS = 90

# Sharding by a distinct_id hash rather than anything team-based: a handful of
# teams carry most of the volume, and sharding by team would hotspot single
# shards. sipHash64 matches the events table's Distributed sharding key, so a
# given distinct_id lands on the same shard in both tables and the events-table
# backfill runs shard-local, with no network shuffle.
FLAG_EVALUATIONS_SHARDING_KEY = "sipHash64(distinct_id)"

# The sort key matches the queries we run: per-flag usage over a date range,
# uniques by distinct_id. No date element here on purpose: PARTITION BY is
# already daily, so a date column in ORDER BY would be constant within every
# part and sort nothing. The trailing hash intentionally differs from the
# sharding key — cityHash64 is the events table's convention for within-shard
# ordering — and a MergeTree ORDER BY is immutable once data exists, so the
# two must not silently move together.
FLAG_EVALUATIONS_ORDER_BY = "(team_id, flag_key, cityHash64(distinct_id))"

# Shared column list (no CODEC clauses — ZSTD applies on the storage side
# only), rendered in two variants via {ts_default}. The Kafka engine table
# must NOT carry the timestamp DEFAULTs: JSONEachRow fills omitted fields
# with the column default, and the MV's legacy-SDK fallbacks detect exactly
# that zero-value sentinel — a DEFAULT there would mask it. The Distributed
# tables MUST carry them: an INSERT through a Distributed table fills omitted
# columns from the Distributed table's own schema before forwarding to the
# shard, so without them a direct insert via writable_flag_evaluations would
# store epoch instead of the sharded table's fallback. The sharded data table
# and the MV's SELECT projection are deliberately not in this sync set — the
# data table inlines the same columns to carry CODEC/INDEX/DEFAULT
# annotations, and the MV hand-lists its output columns — so column changes
# must update all of them in lockstep.
_FLAG_EVALUATIONS_COLUMNS_TEMPLATE = """
    team_id UInt64,
    uuid UUID,
    timestamp DateTime64(6, 'UTC'),
    inserted_at DateTime64(6, 'UTC'){ts_default},
    distinct_id String,
    session_id String,
    device_id String,
    flag_key String,
    response LowCardinality(String),
    flag_id UInt64,
    flag_version UInt32,
    reason LowCardinality(String),
    request_id String,
    evaluated_at DateTime64(6, 'UTC'){ts_default},
    error String,
    locally_evaluated Bool,
    lib LowCardinality(String),
    lib_version LowCardinality(String),
    is_server Bool,
    os LowCardinality(String),
    os_version LowCardinality(String),
    app_version LowCardinality(String),
    current_url String,
    pathname String,
    country_code LowCardinality(String),
    subdivision_1_code LowCardinality(String),
    group_0 String,
    group_1 String,
    group_2 String,
    group_3 String,
    group_4 String
""".strip()

FLAG_EVALUATIONS_KAFKA_COLUMNS = _FLAG_EVALUATIONS_COLUMNS_TEMPLATE.format(ts_default="")
FLAG_EVALUATIONS_DISTRIBUTED_COLUMNS = _FLAG_EVALUATIONS_COLUMNS_TEMPLATE.format(ts_default=" DEFAULT timestamp")


def FLAG_EVALUATIONS_DATA_TABLE_ENGINE() -> MergeTreeEngine:
    # Plain (non-replacing) MergeTree: Kafka replay duplicates are accepted for
    # this telemetry, matching heatmaps. ZK path uses the base table name.
    return MergeTreeEngine(FLAG_EVALUATIONS_TABLE, replication_scheme=ReplicationScheme.SHARDED)


# The actual data lives on the sharded main cluster. ZSTD on the plain String
# columns; LowCardinality columns compress well on their own. Skipping indexes
# cover point lookups the sort key can't serve (a specific user, session, or
# flags-service request). The DEFAULTs — mirrored on both Distributed tables,
# since a Distributed INSERT fills omitted columns from its own schema before
# forwarding — mean a direct insert that omits evaluated_at or inserted_at
# (tests, the planned events-table backfill) falls back to the row's own
# timestamp rather than the wall-clock insert time, so a bulk historical
# backfill doesn't stamp every row as freshly inserted right now: that would
# break anything windowing or checkpointing on inserted_at. Neither DEFAULT
# reproduces the MV's Kafka-path fallback exactly (_timestamp, the Kafka
# broker time, isn't available to a column default), but timestamp is the
# closest available proxy for both columns.
FLAG_EVALUATIONS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {FLAG_EVALUATIONS_DATA_TABLE}
(
    team_id UInt64,
    uuid UUID,
    timestamp DateTime64(6, 'UTC') CODEC(DoubleDelta, ZSTD(1)),
    inserted_at DateTime64(6, 'UTC') DEFAULT timestamp CODEC(DoubleDelta, ZSTD(1)),
    distinct_id String CODEC(ZSTD(1)),
    session_id String CODEC(ZSTD(1)),
    device_id String CODEC(ZSTD(1)),
    flag_key String CODEC(ZSTD(1)),
    response LowCardinality(String),
    flag_id UInt64,
    flag_version UInt32,
    reason LowCardinality(String),
    request_id String CODEC(ZSTD(1)),
    evaluated_at DateTime64(6, 'UTC') DEFAULT timestamp CODEC(DoubleDelta, ZSTD(1)),
    error String CODEC(ZSTD(1)),
    locally_evaluated Bool,
    lib LowCardinality(String),
    lib_version LowCardinality(String),
    is_server Bool,
    os LowCardinality(String),
    os_version LowCardinality(String),
    app_version LowCardinality(String),
    current_url String CODEC(ZSTD(1)),
    pathname String CODEC(ZSTD(1)),
    country_code LowCardinality(String),
    subdivision_1_code LowCardinality(String),
    group_0 String CODEC(ZSTD(1)),
    group_1 String CODEC(ZSTD(1)),
    group_2 String CODEC(ZSTD(1)),
    group_3 String CODEC(ZSTD(1)),
    group_4 String CODEC(ZSTD(1)),
    INDEX distinct_id_idx distinct_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX session_id_idx  session_id  TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX request_id_idx  request_id  TYPE bloom_filter(0.01) GRANULARITY 1
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {FLAG_EVALUATIONS_DATA_TABLE_ENGINE()}
-- Daily partitions: with ttl_only_drop_parts a part only drops when its newest
-- row expires, so monthly partitions would stretch effective retention well
-- past the TTL and reclaim disk in month-sized cliffs.
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY {FLAG_EVALUATIONS_ORDER_BY}
{ttl_period("timestamp", FLAG_EVALUATIONS_TTL_DAYS, unit="DAY")}
SETTINGS ttl_only_drop_parts = 1
"""
)


def _distributed_table_sql(table_name: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {table_name}
(
    {FLAG_EVALUATIONS_DISTRIBUTED_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {Distributed(data_table=FLAG_EVALUATIONS_DATA_TABLE, sharding_key=FLAG_EVALUATIONS_SHARDING_KEY)}
"""


# Fans writes out to sharded_flag_evaluations. Lives on the ingestion layer.
WRITABLE_FLAG_EVALUATIONS_TABLE_SQL = lambda: _distributed_table_sql(FLAG_EVALUATIONS_WRITABLE_TABLE)

# Read path on DATA nodes, and the name queries use.
DISTRIBUTED_FLAG_EVALUATIONS_TABLE_SQL = lambda: _distributed_table_sql(FLAG_EVALUATIONS_TABLE)


# `os_name` exists only here: mobile SDKs send $os_name where browser SDKs send
# $os, and the MV coalesces the two into the single stored `os` column.
KAFKA_FLAG_EVALUATIONS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {KAFKA_FLAG_EVALUATIONS_TABLE}
(
    {FLAG_EVALUATIONS_KAFKA_COLUMNS},
    os_name LowCardinality(String)
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_CLICKHOUSE_FLAG_EVALUATIONS,
            group=CONSUMER_GROUP_FLAG_EVALUATIONS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        )
    }
SETTINGS kafka_skip_broken_messages = 100
"""
)


# The MV defends against absent properties from legacy SDKs: the Kafka
# JSONEachRow parser fills missing fields with the type's zero value, so
# DateTime64 columns read as epoch when a producer omits them. `flag_id` and
# `flag_version` zero-fill to 0, which is the accepted sentinel for "SDK too
# old to send it" — no substitution needed.
_EPOCH_DT64 = "toDateTime64('1970-01-01 00:00:00', 6, 'UTC')"

FLAG_EVALUATIONS_MV_SQL = lambda: (
    f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {FLAG_EVALUATIONS_MV_TABLE}
TO {settings.CLICKHOUSE_DATABASE}.{FLAG_EVALUATIONS_WRITABLE_TABLE}
AS SELECT
    team_id,
    uuid,
    timestamp,
    -- Fall back to the Kafka message timestamp, which is stable across replays
    -- (inserted_at checkpoints the sync_feature_flag_last_called task).
    if(inserted_at = {_EPOCH_DT64}, _timestamp, inserted_at) AS inserted_at,
    distinct_id,
    session_id,
    device_id,
    flag_key,
    response,
    flag_id,
    flag_version,
    reason,
    request_id,
    if(evaluated_at = {_EPOCH_DT64}, timestamp, evaluated_at) AS evaluated_at,
    error,
    locally_evaluated,
    lib,
    lib_version,
    is_server,
    if(os = '', os_name, os) AS os,
    os_version,
    app_version,
    current_url,
    pathname,
    country_code,
    subdivision_1_code,
    group_0,
    group_1,
    group_2,
    group_3,
    group_4,
    _timestamp,
    _offset,
    _partition
FROM {settings.CLICKHOUSE_DATABASE}.{KAFKA_FLAG_EVALUATIONS_TABLE}
"""
)
