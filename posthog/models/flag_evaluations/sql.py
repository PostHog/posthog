from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_FLAG_EVALUATIONS,
    KAFKA_COLUMNS_WITH_PARTITION,
    kafka_engine,
    trim_quotes_expr,
    ttl_period,
)
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_FLAG_EVALUATIONS

# Flag evaluation telemetry ($feature_flag_called events routed out of the events
# table). The column set is the events table's, narrowed to what a flag evaluation
# actually carries: no elements_chain, no person_mode, no *_created_at companions
# to the person and group properties. It keeps the full properties JSON as the
# source of truth, so queries and integrations built on event properties survive
# the routing switch. The 90-day TTL is what makes rows that wide affordable.
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

# The only event this table stores. posthog/models/deletion_targets.py uses it to skip this table
# for deletion requests that name other events, so a producer writing a second event name here has
# to update the target's stored_events.
FLAG_EVALUATIONS_SOURCE_EVENT = "$feature_flag_called"

# Sharding by a distinct_id hash rather than anything team-based: a handful of
# teams carry most of the volume, and sharding by team would hotspot single
# shards. sipHash64 matches the events table's Distributed sharding key, so a
# given distinct_id lands on the same shard in both tables and the events-table
# backfill runs shard-local, with no network shuffle.
FLAG_EVALUATIONS_SHARDING_KEY = "sipHash64(distinct_id)"

# The sort key matches the queries we run: per-flag usage over a date range, and
# uniques within one flag. toDate(timestamp) sits inside it because PARTITION BY
# is monthly — without it, a one-day query for one flag would read that flag's
# whole month. flag_key is a DEFAULT column; ClickHouse fills column defaults at
# insert, before it sorts a part, so one can carry a sort key, though a key
# column can never be ALTER UPDATEd, whatever its kind. The trailing hash intentionally
# differs from the sharding key — cityHash64 is the events table's convention for
# within-shard ordering — and a MergeTree ORDER BY is immutable once data exists,
# so the two must not silently move together.
FLAG_EVALUATIONS_ORDER_BY = "(team_id, flag_key, toDate(timestamp), cityHash64(distinct_id))"

# One canonical column list, rendered in a Kafka, a Distributed and a storage
# variant. Column order follows the events table so converging the two schemas
# later reads as a diff rather than a rewrite.
#
# The Kafka engine table must NOT carry the inserted_at DEFAULT: JSONEachRow fills
# omitted fields with the column default, and the MV's fallback detects exactly
# that zero-value sentinel — a DEFAULT there would mask it. Both Distributed
# tables MUST carry it: an INSERT through a Distributed table fills omitted
# columns from the Distributed table's own schema before forwarding to the shard,
# so without it a direct insert via writable_flag_evaluations would store epoch
# instead of the sharded table's fallback.
#
# No column carries a CODEC, including the JSON blobs the events table wraps in
# ZSTD(3); the general rule is in posthog/clickhouse/migrations/AGENTS.md. Nothing
# here earns an exception: this ORDER BY only buckets timestamp to a day before
# sorting on a distinct_id hash, so the three DateTime64 columns land on disk in
# effectively random order, which is where the delta family loses. Revisit only
# with measurements.
_FLAG_EVALUATIONS_COLUMNS_TEMPLATE = """
    uuid UUID,
    event LowCardinality(String),
    properties String,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id String,
    created_at DateTime64(6, 'UTC'),
    person_id UUID,
    person_properties String,
    group0_properties String,
    group1_properties String,
    group2_properties String,
    group3_properties String,
    group4_properties String,
    inserted_at DateTime64(6, 'UTC'){ts_default}
""".strip()

FLAG_EVALUATIONS_KAFKA_COLUMNS = _FLAG_EVALUATIONS_COLUMNS_TEMPLATE.format(ts_default="")

_FLAG_EVALUATIONS_COLUMNS = _FLAG_EVALUATIONS_COLUMNS_TEMPLATE.format(ts_default=" DEFAULT timestamp")

# Typed copies of properties the hot path cannot afford to parse per row. A
# property earns one only when queries filter or group on it across many rows
# (flag_key, response) or a skip index needs a real column to sit on (session_id,
# request_id). Everything else stays in the properties JSON, and the TTL keeps
# widening this list cheap later.
#
# JSONExtractRaw with the quotes trimmed rather than JSONExtractString. The two
# agree on strings, booleans and numbers, and differ only on JSON null: this form
# stores the literal 'null' that json_extract_trim_quotes and the plugin-server's
# jsonExtractRawAndTrimQuotes both map back to SQL NULL, where JSONExtractString
# stores '' and loses the difference between a null response and an absent
# property. It is also the expression the events table uses for its own
# materialized columns, so both tables encode the same value the same way.
#
# $group_0..$group_4 carry the events table's names, types and comment form so
# group filtering resolves the same columns on both.
#
# DEFAULT rather than MATERIALIZED, the kind materialize() mints on sharded_events:
# both compute the expression when an insert omits the column, but only a DEFAULT
# column accepts ALTER UPDATE, which the events property-removal path relies on to
# reset extracted values whose source property was erased (see
# docs/internal/clickhouse-deletion-coverage.md). An UPDATE of properties does not
# recompute these columns, so a rewrite must reset each affected column in the
# same mutation. The cost is a footgun MATERIALIZED did not have: an insert that
# names one of these columns stores the given value even when it contradicts
# properties. Producers must omit them, which the Kafka path enforces by
# writable_flag_evaluations not declaring them.
_FLAG_EVALUATIONS_TYPED_COLUMNS = f"""
    , $group_0 String DEFAULT {trim_quotes_expr("JSONExtractRaw(properties, '$group_0')")} COMMENT 'column_materializer::$group_0'
    , $group_1 String DEFAULT {trim_quotes_expr("JSONExtractRaw(properties, '$group_1')")} COMMENT 'column_materializer::$group_1'
    , $group_2 String DEFAULT {trim_quotes_expr("JSONExtractRaw(properties, '$group_2')")} COMMENT 'column_materializer::$group_2'
    , $group_3 String DEFAULT {trim_quotes_expr("JSONExtractRaw(properties, '$group_3')")} COMMENT 'column_materializer::$group_3'
    , $group_4 String DEFAULT {trim_quotes_expr("JSONExtractRaw(properties, '$group_4')")} COMMENT 'column_materializer::$group_4'
    , flag_key String DEFAULT {trim_quotes_expr("JSONExtractRaw(properties, '$feature_flag')")} COMMENT 'column_materializer::properties::$feature_flag'
    , response LowCardinality(String) DEFAULT {trim_quotes_expr("JSONExtractRaw(properties, '$feature_flag_response')")} COMMENT 'column_materializer::properties::$feature_flag_response'
    , session_id String DEFAULT {trim_quotes_expr("JSONExtractRaw(properties, '$session_id')")} COMMENT 'column_materializer::properties::$session_id'
    , request_id String DEFAULT {trim_quotes_expr("JSONExtractRaw(properties, '$feature_flag_request_id')")} COMMENT 'column_materializer::properties::$feature_flag_request_id'
"""

# A Distributed engine computes nothing, so the read table repeats the same names
# and types without the expression, which is what lets a query against
# flag_evaluations select the columns the shards store. The writable table omits
# them entirely: carrying the DEFAULT expressions there would compute the values
# on the ingestion nodes and ship the widened rows over the network, so rows
# arrive narrow and the shard computes them, matching writable_events.
_FLAG_EVALUATIONS_PROXY_TYPED_COLUMNS = """
    , $group_0 String COMMENT 'column_materializer::$group_0'
    , $group_1 String COMMENT 'column_materializer::$group_1'
    , $group_2 String COMMENT 'column_materializer::$group_2'
    , $group_3 String COMMENT 'column_materializer::$group_3'
    , $group_4 String COMMENT 'column_materializer::$group_4'
    , flag_key String COMMENT 'column_materializer::properties::$feature_flag'
    , response LowCardinality(String) COMMENT 'column_materializer::properties::$feature_flag_response'
    , session_id String COMMENT 'column_materializer::properties::$session_id'
    , request_id String COMMENT 'column_materializer::properties::$feature_flag_request_id'
"""

# The bloom filters cover point lookups the sort key can't serve (a specific user,
# person, session, or flags-service request). The minmax on inserted_at serves
# incremental consumers that checkpoint on it: partitioning is on timestamp, so an
# inserted_at range predicate prunes no partitions on its own and would otherwise
# read all 90 days. A skip index only covers parts written after it exists, so
# retrofitting one means a full MATERIALIZE INDEX mutation — much cheaper to
# declare up front.
_FLAG_EVALUATIONS_INDEXES = """
    , INDEX distinct_id_idx distinct_id TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX person_id_idx   person_id   TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX session_id_idx  session_id  TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX request_id_idx  request_id  TYPE bloom_filter(0.01) GRANULARITY 1
    , INDEX inserted_at_idx inserted_at TYPE minmax GRANULARITY 1
"""


def FLAG_EVALUATIONS_DATA_TABLE_ENGINE() -> MergeTreeEngine:
    # Plain (non-replacing) MergeTree: Kafka replay duplicates are accepted for
    # this telemetry, matching heatmaps. ZK path uses the base table name.
    return MergeTreeEngine(FLAG_EVALUATIONS_TABLE, replication_scheme=ReplicationScheme.SHARDED)


# The actual data lives on the sharded main cluster.
#
# The inserted_at DEFAULT means a direct insert that omits it (tests, the planned
# events-table backfill) falls back to the row's own timestamp rather than the
# wall-clock insert time, so a bulk historical backfill doesn't stamp every row as
# freshly inserted right now: that would break anything windowing or checkpointing
# on inserted_at. It doesn't reproduce the MV's Kafka-path fallback exactly
# (_timestamp, the Kafka broker time, isn't available to a column default), but
# timestamp is the closest available proxy.
FLAG_EVALUATIONS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {FLAG_EVALUATIONS_DATA_TABLE}
(
    {_FLAG_EVALUATIONS_COLUMNS}
    {_FLAG_EVALUATIONS_TYPED_COLUMNS}
    {_FLAG_EVALUATIONS_INDEXES}
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


def DROP_FLAG_EVALUATIONS_PROXY_TABLES_SQL() -> list[str]:
    """Drop the two Distributed fronts so a reset recreates them alongside the storage table.

    Recreating the shard while leaving these on an older column list makes inserts silently drop
    the new column and reads not see it, which fails as a puzzle rather than as a schema error.
    """
    return [
        f"DROP TABLE IF EXISTS {FLAG_EVALUATIONS_TABLE}",
        f"DROP TABLE IF EXISTS {FLAG_EVALUATIONS_WRITABLE_TABLE}",
    ]


def DROP_FLAG_EVALUATIONS_TABLE_SQL() -> str:
    # reset_clickhouse_database drops rather than truncates because MutationRunner skips enqueueing
    # a mutation whose command text already exists on the table, so mutation history left behind by
    # one test turns a later test's identical delete into a no-op. SYNC so the replica's ZooKeeper
    # metadata is gone before the table is recreated.
    return f"DROP TABLE IF EXISTS {FLAG_EVALUATIONS_DATA_TABLE} SYNC"


def _distributed_table_sql(table_name: str, *, typed_columns: str = "") -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {table_name}
(
    {_FLAG_EVALUATIONS_COLUMNS}
    {typed_columns}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {Distributed(data_table=FLAG_EVALUATIONS_DATA_TABLE, sharding_key=FLAG_EVALUATIONS_SHARDING_KEY)}
"""


# Fans writes out to sharded_flag_evaluations. Lives on the ingestion layer.
WRITABLE_FLAG_EVALUATIONS_TABLE_SQL = lambda: _distributed_table_sql(FLAG_EVALUATIONS_WRITABLE_TABLE)

# Read path on DATA nodes, and the name queries use.
DISTRIBUTED_FLAG_EVALUATIONS_TABLE_SQL = lambda: _distributed_table_sql(
    FLAG_EVALUATIONS_TABLE, typed_columns=_FLAG_EVALUATIONS_PROXY_TYPED_COLUMNS
)


KAFKA_FLAG_EVALUATIONS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {KAFKA_FLAG_EVALUATIONS_TABLE}
(
    {FLAG_EVALUATIONS_KAFKA_COLUMNS}
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


# The Kafka JSONEachRow parser fills missing fields with the type's zero value, so
# a DateTime64 column reads as epoch when a producer omits it.
_EPOCH_DT64 = "toDateTime64('1970-01-01 00:00:00', 6, 'UTC')"

FLAG_EVALUATIONS_MV_SQL = lambda: (
    f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {FLAG_EVALUATIONS_MV_TABLE}
TO {settings.CLICKHOUSE_DATABASE}.{FLAG_EVALUATIONS_WRITABLE_TABLE}
AS SELECT
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    created_at,
    person_id,
    person_properties,
    group0_properties,
    group1_properties,
    group2_properties,
    group3_properties,
    group4_properties,
    -- Fall back to the Kafka message timestamp, which is stable across replays
    -- (inserted_at checkpoints the sync_feature_flag_last_called task, and an
    -- epoch-stamped row would stay invisible to it forever).
    if(inserted_at = {_EPOCH_DT64}, _timestamp, inserted_at) AS inserted_at,
    _timestamp,
    _offset,
    _partition
FROM {settings.CLICKHOUSE_DATABASE}.{KAFKA_FLAG_EVALUATIONS_TABLE}
"""
)
