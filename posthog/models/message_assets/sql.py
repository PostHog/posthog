from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_MESSAGE_ASSETS,
    KAFKA_COLUMNS_WITH_PARTITION,
    kafka_engine,
    ttl_period,
)
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_MESSAGE_ASSETS

MESSAGE_ASSETS_TTL_DAYS = 30

# Layout mirrors `hog_invocation_results` — the AUX-resident, non-sharded table
# family produced by the CDP cyclotron path:
#   * `message_assets_data` — local replicated table on AUX. Writes flow in via
#     the Kafka MV; reads happen against the distributed alias.
#   * `kafka_message_assets` — single Kafka engine table on AUX backed by the
#     warpstream-cyclotron named collection (same producer cluster as
#     hog_invocation_results).
#   * `message_assets_mv` — MV on AUX, kafka → data table.
#   * `message_assets` — distributed read alias on AUX + DATA. This is the name
#     HogQL emits and the name the assets API queries.
#
# One row per successfully sent email, keyed by (invocation_id, action_id) — a
# single workflow invocation can fan out to multiple email steps. The rendered
# HTML body lives inline in the `html` column (ZSTD-compressed); columnar
# storage means the listing query never reads it.
MESSAGE_ASSETS_TABLE = "message_assets"
MESSAGE_ASSETS_DATA_TABLE = f"{MESSAGE_ASSETS_TABLE}_data"
KAFKA_MESSAGE_ASSETS_TABLE = f"kafka_{MESSAGE_ASSETS_TABLE}"
MESSAGE_ASSETS_MV_TABLE = f"{MESSAGE_ASSETS_TABLE}_mv"


def DROP_MESSAGE_ASSETS_MV_SQL() -> str:
    return f"DROP TABLE IF EXISTS {MESSAGE_ASSETS_MV_TABLE}"


def DROP_KAFKA_MESSAGE_ASSETS_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {KAFKA_MESSAGE_ASSETS_TABLE}"


def MESSAGE_ASSETS_ENGINE() -> ReplacingMergeTree:
    # ReplicatedReplacingMergeTree on the AUX cluster — single shard, two
    # replicas. `version` tie-breaks so a duplicate produce (e.g. a retried
    # Kafka send for the same asset) collapses to the latest row at merge time.
    return ReplacingMergeTree(
        MESSAGE_ASSETS_DATA_TABLE,
        ver="version",
        replication_scheme=ReplicationScheme.REPLICATED,
    )


# Kafka payload column list — reused between the Kafka engine table, the MV
# projection, and the distributed read alias. `html` is last because it dominates
# row size; column-oriented reads mean listing queries never touch it.
MESSAGE_ASSETS_KAFKA_COLUMNS = """
    team_id Int64,
    function_kind LowCardinality(String),
    function_id String,
    parent_run_id String,
    invocation_id String,
    action_id String,
    kind LowCardinality(String),
    distinct_id String,
    person_id String,
    recipient String,
    subject String,
    status LowCardinality(String),
    sent_at DateTime64(6, 'UTC'),
    version UInt64,
    is_deleted UInt8,
    html String
""".strip()


# The data lives on AUX. Skipping indexes match the listing query shape: filter
# by function_id (workflow) + optional parent_run_id (batch run), and search by
# recipient / distinct_id / person.
MESSAGE_ASSETS_DATA_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {MESSAGE_ASSETS_DATA_TABLE}
(
    team_id Int64,
    function_kind LowCardinality(String),
    function_id String,
    parent_run_id String,
    invocation_id String,
    action_id String,
    kind LowCardinality(String),
    distinct_id String,
    person_id String,
    recipient String,
    subject String,
    status LowCardinality(String),
    sent_at DateTime64(6, 'UTC'),
    version UInt64,
    is_deleted UInt8 DEFAULT 0,
    html String CODEC(ZSTD(3)),
    INDEX parent_run_idx parent_run_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX distinct_id_idx distinct_id  TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX person_id_idx   person_id    TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX recipient_idx   recipient    TYPE bloom_filter(0.01) GRANULARITY 1
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {MESSAGE_ASSETS_ENGINE()}
PARTITION BY toYYYYMMDD(sent_at)
ORDER BY (team_id, function_kind, function_id, invocation_id, action_id)
{ttl_period("sent_at", MESSAGE_ASSETS_TTL_DAYS, unit="DAY")}
SETTINGS index_granularity = 1024, ttl_only_drop_parts = 1
"""
)


# Distributed read alias. Created on both AUX (so AUX-local queries work) and
# DATA (so HogQL queries from the main cluster reach the data).
DISTRIBUTED_MESSAGE_ASSETS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {MESSAGE_ASSETS_TABLE}
(
    {MESSAGE_ASSETS_KAFKA_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {Distributed(data_table=MESSAGE_ASSETS_DATA_TABLE, cluster=settings.CLICKHOUSE_AUX_CLUSTER)}
"""
)


# Single Kafka pair, backed by the warpstream-cyclotron named collection — the
# CDP producer writes asset rows to the cyclotron Warpstream cluster, the same
# cluster hog_invocation_results uses.
KAFKA_MESSAGE_ASSETS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {KAFKA_MESSAGE_ASSETS_TABLE}
(
    {MESSAGE_ASSETS_KAFKA_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_MESSAGE_ASSETS,
            group=CONSUMER_GROUP_MESSAGE_ASSETS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_CYCLOTRON_NAMED_COLLECTION,
        )
    }
SETTINGS kafka_skip_broken_messages = 100
"""
)


# MV runs on AUX, writes straight into the local data table.
MESSAGE_ASSETS_MV_SQL = lambda target_table=MESSAGE_ASSETS_DATA_TABLE: (
    f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {MESSAGE_ASSETS_MV_TABLE}
TO {target_table}
AS SELECT
    team_id,
    function_kind,
    function_id,
    parent_run_id,
    invocation_id,
    action_id,
    kind,
    distinct_id,
    person_id,
    recipient,
    subject,
    status,
    sent_at,
    version,
    is_deleted,
    html,
    _timestamp,
    _offset,
    _partition
FROM {KAFKA_MESSAGE_ASSETS_TABLE}
"""
)


TRUNCATE_MESSAGE_ASSETS_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {MESSAGE_ASSETS_DATA_TABLE}"


# Direct insert used by tests / any bypass-Kafka producer. Writes go to the
# local data table (the distributed read alias isn't writable).
INSERT_MESSAGE_ASSET_SQL = f"""
INSERT INTO {MESSAGE_ASSETS_DATA_TABLE} (
    team_id,
    function_kind,
    function_id,
    parent_run_id,
    invocation_id,
    action_id,
    kind,
    distinct_id,
    person_id,
    recipient,
    subject,
    status,
    sent_at,
    version,
    is_deleted,
    html,
    _timestamp,
    _offset,
    _partition
)
SELECT
    %(team_id)s,
    %(function_kind)s,
    %(function_id)s,
    %(parent_run_id)s,
    %(invocation_id)s,
    %(action_id)s,
    %(kind)s,
    %(distinct_id)s,
    %(person_id)s,
    %(recipient)s,
    %(subject)s,
    %(status)s,
    %(sent_at)s,
    %(version)s,
    %(is_deleted)s,
    %(html)s,
    now(),
    0,
    0
"""
