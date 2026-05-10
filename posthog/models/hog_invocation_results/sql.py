from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_HOG_INVOCATION_RESULTS,
    CONSUMER_GROUP_HOG_INVOCATION_RESULTS_WS,
    KAFKA_COLUMNS_WITH_PARTITION,
    kafka_engine,
    ttl_period,
)
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_HOG_INVOCATION_RESULTS
from posthog.settings.data_stores import CLICKHOUSE_SINGLE_SHARD_CLUSTER

HOG_INVOCATION_RESULTS_TTL_DAYS = 30

HOG_INVOCATION_RESULTS_TABLE = "hog_invocation_results"
HOG_INVOCATION_RESULTS_SHARDED_TABLE = f"sharded_{HOG_INVOCATION_RESULTS_TABLE}"
HOG_INVOCATION_RESULTS_WRITABLE_TABLE = f"writable_{HOG_INVOCATION_RESULTS_TABLE}"
KAFKA_HOG_INVOCATION_RESULTS_TABLE = f"kafka_{HOG_INVOCATION_RESULTS_TABLE}"
HOG_INVOCATION_RESULTS_MV_TABLE = f"{HOG_INVOCATION_RESULTS_TABLE}_mv"

KAFKA_HOG_INVOCATION_RESULTS_WS_TABLE = f"kafka_{HOG_INVOCATION_RESULTS_TABLE}_ws"
HOG_INVOCATION_RESULTS_WS_MV_TABLE = f"{HOG_INVOCATION_RESULTS_TABLE}_ws_mv"


def DROP_HOG_INVOCATION_RESULTS_MV_SQL() -> str:
    return f"DROP TABLE IF EXISTS {HOG_INVOCATION_RESULTS_MV_TABLE}"


def DROP_KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {KAFKA_HOG_INVOCATION_RESULTS_TABLE}"


def DROP_HOG_INVOCATION_RESULTS_WS_MV_SQL() -> str:
    return f"DROP TABLE IF EXISTS {HOG_INVOCATION_RESULTS_WS_MV_TABLE}"


def DROP_KAFKA_HOG_INVOCATION_RESULTS_WS_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {KAFKA_HOG_INVOCATION_RESULTS_WS_TABLE}"


# Kafka payload columns. ZSTD-compressed columns must NOT be declared as such in
# the Kafka engine table — Kafka's JSONEachRow ingest is already plain text, the
# CODEC only applies on the storage side. The columns are listed identically in
# both Kafka and storage tables; the CODEC lives only on the sharded table below.
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


def HOG_INVOCATION_RESULTS_SHARDED_TABLE_ENGINE() -> ReplacingMergeTree:
    return ReplacingMergeTree(
        HOG_INVOCATION_RESULTS_SHARDED_TABLE,
        ver="version",
        replication_scheme=ReplicationScheme.SHARDED,
    )


# Storage layout:
# - sharded_hog_invocation_results: replicated + sharded source-of-truth, one row per
#   lifecycle event. ZSTD on the two big String columns. ReplacingMergeTree keyed by
#   `version` collapses lifecycle events for the same invocation_id at merge time.
# - writable_hog_invocation_results: Distributed-engine write target on the ingestion
#   layer. Materialized views write here; the rows are sharded across the cluster by
#   `cityHash64(invocation_id)` so all rows for an invocation land on the same shard
#   (so the ReplacingMergeTree can merge them).
# - hog_invocation_results: Distributed-engine read target on data nodes. This is the
#   table HogQL queries point at.
HOG_INVOCATION_RESULTS_DATA_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS {HOG_INVOCATION_RESULTS_SHARDED_TABLE}
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
    started_at Nullable(DateTime64(6, 'UTC')),
    finished_at Nullable(DateTime64(6, 'UTC')),
    duration_ms Nullable(UInt32),
    error_kind LowCardinality(String),
    error_message String CODEC(ZSTD(3)),
    event_uuid String,
    distinct_id String,
    person_id String,
    invocation_globals String CODEC(ZSTD(3)),
    version UInt64,
    is_deleted UInt8 DEFAULT 0,
    INDEX status_idx     status      TYPE set(8)             GRANULARITY 4,
    INDEX function_idx   function_id TYPE bloom_filter(0.01) GRANULARITY 4,
    INDEX event_uuid_idx event_uuid  TYPE bloom_filter(0.01) GRANULARITY 4,
    INDEX is_retry_idx   is_retry    TYPE set(2)             GRANULARITY 4
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {HOG_INVOCATION_RESULTS_SHARDED_TABLE_ENGINE()}
PARTITION BY toYYYYMMDD(scheduled_at)
ORDER BY (team_id, function_kind, function_id, invocation_id)
{ttl_period("scheduled_at", HOG_INVOCATION_RESULTS_TTL_DAYS, unit="DAY")}
SETTINGS index_granularity = 1024, ttl_only_drop_parts = 1
"""
)


# Distributed read alias on data nodes (HogQL points here).
DISTRIBUTED_HOG_INVOCATION_RESULTS_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS {HOG_INVOCATION_RESULTS_TABLE}
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
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {Distributed(data_table=HOG_INVOCATION_RESULTS_SHARDED_TABLE, sharding_key="cityHash64(invocation_id)")}
"""
)


# Distributed write alias on the ingestion layer. Same shape as the read alias.
WRITABLE_HOG_INVOCATION_RESULTS_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS {HOG_INVOCATION_RESULTS_WRITABLE_TABLE}
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
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {Distributed(data_table=HOG_INVOCATION_RESULTS_SHARDED_TABLE, sharding_key="cityHash64(invocation_id)")}
"""
)


KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS {KAFKA_HOG_INVOCATION_RESULTS_TABLE}
(
    {HOG_INVOCATION_RESULTS_KAFKA_COLUMNS}
)
ENGINE = {kafka_engine(topic=KAFKA_HOG_INVOCATION_RESULTS, group=CONSUMER_GROUP_HOG_INVOCATION_RESULTS)}
"""
)


HOG_INVOCATION_RESULTS_MV_SQL = (
    lambda target_table=HOG_INVOCATION_RESULTS_WRITABLE_TABLE: f"""
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


# WarpStream Kafka engine variants — coexist alongside MSK during the cut-over.
KAFKA_HOG_INVOCATION_RESULTS_WS_TABLE_SQL = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS {KAFKA_HOG_INVOCATION_RESULTS_WS_TABLE}
(
    {HOG_INVOCATION_RESULTS_KAFKA_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_HOG_INVOCATION_RESULTS,
            group=CONSUMER_GROUP_HOG_INVOCATION_RESULTS_WS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        )
    }
"""
)


HOG_INVOCATION_RESULTS_WS_MV_SQL = (
    lambda target_table=HOG_INVOCATION_RESULTS_WRITABLE_TABLE: f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {HOG_INVOCATION_RESULTS_WS_MV_TABLE}
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
FROM {KAFKA_HOG_INVOCATION_RESULTS_WS_TABLE}
"""
)


TRUNCATE_HOG_INVOCATION_RESULTS_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {HOG_INVOCATION_RESULTS_SHARDED_TABLE}"


# Direct insert SQL used by tests and any bypass-Kafka producers.
INSERT_HOG_INVOCATION_RESULT_SQL = """
INSERT INTO sharded_hog_invocation_results (
    team_id,
    function_kind,
    function_id,
    invocation_id,
    parent_run_id,
    status,
    attempts,
    is_retry,
    scheduled_at,
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


# Re-exported for clarity at call sites.
HOG_INVOCATION_RESULTS_SINGLE_SHARD_CLUSTER = CLICKHOUSE_SINGLE_SHARD_CLUSTER
