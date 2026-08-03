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
# uniques by distinct_id. toDate(timestamp) sits inside it because PARTITION BY
# is monthly — without it, a one-day query for one flag would read that flag's
# whole month. The trailing hash intentionally differs from the sharding key —
# cityHash64 is the events table's convention for within-shard ordering — and a
# MergeTree ORDER BY is immutable once data exists, so the two must not silently
# move together.
FLAG_EVALUATIONS_ORDER_BY = "(team_id, flag_key, toDate(timestamp), cityHash64(distinct_id))"

# One canonical column list, rendered in a Kafka variant and a storage variant.
#
# The Kafka engine table must NOT carry the timestamp DEFAULTs: JSONEachRow
# fills omitted fields with the column default, and the MV's legacy-SDK
# fallbacks detect exactly that zero-value sentinel — a DEFAULT there would mask
# it. Both Distributed tables MUST carry them: an INSERT through a Distributed
# table fills omitted columns from the Distributed table's own schema before
# forwarding to the shard, so without them a direct insert via
# writable_flag_evaluations would store epoch instead of the sharded table's
# fallback. That makes the Distributed and sharded column lists identical, which
# is also how the events family declares its CODECs.
_FLAG_EVALUATIONS_COLUMNS_TEMPLATE = """
    team_id Int64,
    uuid UUID,
    timestamp DateTime64(6, 'UTC'){dt_codec},
    inserted_at DateTime64(6, 'UTC'){ts_default}{dt_codec},
    distinct_id String{codec},
    session_id String{codec},
    device_id String{codec},
    flag_key String{codec},
    response LowCardinality(String),
    flag_id UInt64,
    flag_version UInt32,
    reason LowCardinality(String),
    request_id String{codec},
    evaluated_at DateTime64(6, 'UTC'){ts_default}{dt_codec},
    error String{codec},
    locally_evaluated Bool,
    lib LowCardinality(String),
    lib_version LowCardinality(String),
    is_server Bool,
    os LowCardinality(String),
    os_version LowCardinality(String),
    app_version LowCardinality(String),
    current_url String{codec},
    pathname String{codec},
    country_code LowCardinality(String),
    subdivision_1_code LowCardinality(String),
    group_0 String{codec},
    group_1 String{codec},
    group_2 String{codec},
    group_3 String{codec},
    group_4 String{codec}
""".strip()

FLAG_EVALUATIONS_KAFKA_COLUMNS = _FLAG_EVALUATIONS_COLUMNS_TEMPLATE.format(ts_default="", codec="", dt_codec="")

# ZSTD on the plain String columns and DoubleDelta on the timestamps;
# LowCardinality columns compress well on their own.
_FLAG_EVALUATIONS_STORAGE_COLUMNS = _FLAG_EVALUATIONS_COLUMNS_TEMPLATE.format(
    ts_default=" DEFAULT timestamp",
    codec=" CODEC(ZSTD(1))",
    dt_codec=" CODEC(DoubleDelta, ZSTD(1))",
)


def FLAG_EVALUATIONS_DATA_TABLE_ENGINE() -> MergeTreeEngine:
    # Plain (non-replacing) MergeTree: Kafka replay duplicates are accepted for
    # this telemetry, matching heatmaps. ZK path uses the base table name.
    return MergeTreeEngine(FLAG_EVALUATIONS_TABLE, replication_scheme=ReplicationScheme.SHARDED)


# The actual data lives on the sharded main cluster.
#
# The bloom filters cover point lookups the sort key can't serve (a specific
# user, session, or flags-service request). The minmax on inserted_at serves
# incremental consumers that checkpoint on it: partitioning is on timestamp, so
# an inserted_at range predicate prunes no partitions on its own and would
# otherwise read all 90 days. A skip index only covers parts written after it
# exists, so retrofitting one means a full MATERIALIZE INDEX mutation — much
# cheaper to declare up front.
#
# The DEFAULTs mean a direct insert that omits evaluated_at or inserted_at
# (tests, the planned events-table backfill) falls back to the row's own
# timestamp rather than the wall-clock insert time, so a bulk historical
# backfill doesn't stamp every row as freshly inserted right now: that would
# break anything windowing or checkpointing on inserted_at. Neither DEFAULT
# reproduces the MV's Kafka-path fallback exactly (_timestamp, the Kafka broker
# time, isn't available to a column default), but timestamp is the closest
# available proxy for both columns.
FLAG_EVALUATIONS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {FLAG_EVALUATIONS_DATA_TABLE}
(
    {_FLAG_EVALUATIONS_STORAGE_COLUMNS},
    INDEX distinct_id_idx distinct_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX session_id_idx  session_id  TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX request_id_idx  request_id  TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX inserted_at_idx inserted_at TYPE minmax GRANULARITY 1
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {FLAG_EVALUATIONS_DATA_TABLE_ENGINE()}
-- Monthly, matching the events family. Daily partitions would put ~90 of them
-- under a 90-day TTL, and enough parts across them to strain merges. The cost
-- is coarser expiry: with ttl_only_drop_parts a part only drops once its newest
-- row expires, so rows survive up to a month past the TTL.
PARTITION BY toYYYYMM(timestamp)
ORDER BY {FLAG_EVALUATIONS_ORDER_BY}
{ttl_period("timestamp", FLAG_EVALUATIONS_TTL_DAYS, unit="DAY")}
SETTINGS ttl_only_drop_parts = 1
"""
)


def _distributed_table_sql(table_name: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {table_name}
(
    {_FLAG_EVALUATIONS_STORAGE_COLUMNS}
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
