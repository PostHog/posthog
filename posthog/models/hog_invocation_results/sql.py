from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_HOG_INVOCATION_RESULTS,
    KAFKA_COLUMNS_WITH_PARTITION,
    kafka_engine,
    ttl_period,
)
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_HOG_INVOCATION_RESULTS

HOG_INVOCATION_RESULTS_TTL_DAYS = 30

# Naming convention mirrors `property_values` — the AUX-resident, non-sharded
# table family:
#   * `hog_invocation_results_data` — local replicated table on AUX. Writes flow
#     in via the Kafka MV; replay reads happen against the distributed alias.
#   * `kafka_hog_invocation_results` — single Kafka engine table on AUX backed
#     by the warpstream-cyclotron named collection.
#   * `hog_invocation_results_mv` — MV on AUX, kafka → data table.
#   * `hog_invocation_results` — distributed read alias on AUX + DATA. This is
#     the name HogQL emits and the name the replay paginator queries.
HOG_INVOCATION_RESULTS_TABLE = "hog_invocation_results"
HOG_INVOCATION_RESULTS_DATA_TABLE = f"{HOG_INVOCATION_RESULTS_TABLE}_data"
KAFKA_HOG_INVOCATION_RESULTS_TABLE = f"kafka_{HOG_INVOCATION_RESULTS_TABLE}"
HOG_INVOCATION_RESULTS_MV_TABLE = f"{HOG_INVOCATION_RESULTS_TABLE}_mv"


def DROP_HOG_INVOCATION_RESULTS_MV_SQL() -> str:
    return f"DROP TABLE IF EXISTS {HOG_INVOCATION_RESULTS_MV_TABLE}"


def DROP_KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {KAFKA_HOG_INVOCATION_RESULTS_TABLE}"


def HOG_INVOCATION_RESULTS_ENGINE() -> ReplacingMergeTree:
    # ReplicatedReplacingMergeTree on the AUX cluster — single shard, two
    # replicas. The `version` column tie-breaks: lifecycle rows for the same
    # invocation_id (start + finish, plus any replay attempts) collapse to the
    # latest version at merge time.
    return ReplacingMergeTree(
        HOG_INVOCATION_RESULTS_DATA_TABLE,
        ver="version",
        replication_scheme=ReplicationScheme.REPLICATED,
    )


# Kafka payload column list (no CODEC clauses — ZSTD applies on the storage
# side only). Reused between the Kafka engine table, the MV projection, and
# the distributed read alias.
#
# `first_scheduled_at` is set by the producer to the *original* cyclotron-
# scheduled time and carried unchanged through retries. The ReplacingMergeTree
# collapses rows per `invocation_id`, so we couldn't recover the original
# scheduled time with `min(scheduled_at)` post-merge — every lifecycle row
# for a given invocation carries this column verbatim so `argMax(..., version)`
# returns it correctly regardless of merge state.
HOG_INVOCATION_RESULTS_KAFKA_COLUMNS = """
    team_id Int64,
    function_kind LowCardinality(String),
    function_id String,
    invocation_id String,
    parent_run_id String,
    status LowCardinality(String),
    attempts UInt8,
    is_retry UInt8,
    scheduled_at DateTime64(6, 'UTC'),
    first_scheduled_at DateTime64(6, 'UTC'),
    started_at Nullable(DateTime64(6, 'UTC')),
    finished_at Nullable(DateTime64(6, 'UTC')),
    duration_ms Nullable(UInt32),
    error_kind LowCardinality(String),
    error_message String,
    event_uuid String,
    distinct_id String,
    person_id String,
    invocation_globals String,
    version UInt64,
    is_deleted UInt8
""".strip()


# The actual data lives on AUX. ZSTD on the two large String columns. Skipping
# indexes match the listing/replay query shape — see the runs-v2 logic for
# the canonical select.
HOG_INVOCATION_RESULTS_DATA_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {HOG_INVOCATION_RESULTS_DATA_TABLE}
(
    team_id Int64,
    function_kind LowCardinality(String),
    function_id String,
    invocation_id String,
    parent_run_id String,
    status LowCardinality(String),
    attempts UInt8,
    is_retry UInt8,
    scheduled_at DateTime64(6, 'UTC'),
    first_scheduled_at DateTime64(6, 'UTC') DEFAULT scheduled_at,
    started_at Nullable(DateTime64(6, 'UTC')),
    finished_at Nullable(DateTime64(6, 'UTC')),
    duration_ms Nullable(UInt32),
    error_kind LowCardinality(String),
    error_message String,
    event_uuid String,
    distinct_id String,
    person_id String,
    invocation_globals String,
    version UInt64,
    is_deleted UInt8 DEFAULT 0,
    INDEX status_idx     status      TYPE set(8)             GRANULARITY 1,
    INDEX function_idx   function_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX event_uuid_idx event_uuid  TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX is_retry_idx   is_retry    TYPE set(2)             GRANULARITY 1
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {HOG_INVOCATION_RESULTS_ENGINE()}
PARTITION BY toYYYYMMDD(scheduled_at)
ORDER BY (team_id, function_kind, function_id, invocation_id)
{ttl_period("scheduled_at", HOG_INVOCATION_RESULTS_TTL_DAYS, unit="DAY")}
SETTINGS index_granularity = 1024, ttl_only_drop_parts = 1
"""
)


# Distributed read alias. Created on both AUX (so AUX-local queries work) and
# DATA (so HogQL queries from the main cluster reach the data). Replay paginator
# also queries this. cluster=settings.CLICKHOUSE_AUX_CLUSTER so the Distributed
# engine routes lookups to the AUX replicas.
DISTRIBUTED_HOG_INVOCATION_RESULTS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {HOG_INVOCATION_RESULTS_TABLE}
(
    {HOG_INVOCATION_RESULTS_KAFKA_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {Distributed(data_table=HOG_INVOCATION_RESULTS_DATA_TABLE, cluster=settings.CLICKHOUSE_AUX_CLUSTER)}
"""
)


# Single Kafka pair, backed by the warpstream-cyclotron named collection — the
# CDP producer writes lifecycle rows to the cyclotron Warpstream cluster. We
# previously also created an MSK-backed pair alongside this; that's gone — the
# producer writes to one topic and one consumer drains it.
KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {KAFKA_HOG_INVOCATION_RESULTS_TABLE}
(
    {HOG_INVOCATION_RESULTS_KAFKA_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_HOG_INVOCATION_RESULTS,
            group=CONSUMER_GROUP_HOG_INVOCATION_RESULTS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_CYCLOTRON_NAMED_COLLECTION,
        )
    }
SETTINGS kafka_skip_broken_messages = 100
"""
)


# MV runs on AUX, writes straight into the local data table. No writable
# distributed wrapper needed — single-shard cluster means there's nothing to
# fan out to.
HOG_INVOCATION_RESULTS_MV_SQL = lambda target_table=HOG_INVOCATION_RESULTS_DATA_TABLE: (
    f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {HOG_INVOCATION_RESULTS_MV_TABLE}
TO {target_table}
AS SELECT
    team_id,
    function_kind,
    function_id,
    invocation_id,
    parent_run_id,
    status,
    attempts,
    is_retry,
    scheduled_at,
    -- Defensive fallback: if the producer omits the field (e.g. an older build
    -- still in rollout), the Kafka JSONEachRow parser populates the column
    -- with epoch 0. Substitute `scheduled_at` in that case so the column reads
    -- sensibly. Once every producer carries the field, this resolves to a
    -- straight passthrough.
    if(first_scheduled_at = toDateTime64('1970-01-01 00:00:00', 6, 'UTC'), scheduled_at, first_scheduled_at) AS first_scheduled_at,
    started_at,
    finished_at,
    duration_ms,
    error_kind,
    error_message,
    event_uuid,
    distinct_id,
    person_id,
    invocation_globals,
    version,
    is_deleted,
    _timestamp,
    _offset,
    _partition
FROM {KAFKA_HOG_INVOCATION_RESULTS_TABLE}
"""
)


TRUNCATE_HOG_INVOCATION_RESULTS_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {HOG_INVOCATION_RESULTS_DATA_TABLE}"


# Direct insert used by tests / any bypass-Kafka producer. Writes go to the
# local data table (the distributed read alias isn't writable).
INSERT_HOG_INVOCATION_RESULT_SQL = f"""
INSERT INTO {HOG_INVOCATION_RESULTS_DATA_TABLE} (
    team_id,
    function_kind,
    function_id,
    invocation_id,
    parent_run_id,
    status,
    attempts,
    is_retry,
    scheduled_at,
    first_scheduled_at,
    started_at,
    finished_at,
    duration_ms,
    error_kind,
    error_message,
    event_uuid,
    distinct_id,
    person_id,
    invocation_globals,
    version,
    is_deleted,
    _timestamp,
    _offset,
    _partition
)
SELECT
    %(team_id)s,
    %(function_kind)s,
    %(function_id)s,
    %(invocation_id)s,
    %(parent_run_id)s,
    %(status)s,
    %(attempts)s,
    %(is_retry)s,
    %(scheduled_at)s,
    %(first_scheduled_at)s,
    %(started_at)s,
    %(finished_at)s,
    %(duration_ms)s,
    %(error_kind)s,
    %(error_message)s,
    %(event_uuid)s,
    %(distinct_id)s,
    %(person_id)s,
    %(invocation_globals)s,
    %(version)s,
    %(is_deleted)s,
    now(),
    0,
    0
"""
