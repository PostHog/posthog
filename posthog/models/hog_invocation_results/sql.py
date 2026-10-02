from django.conf import settings

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_HOG_INVOCATION_RESULTS, kafka_engine
from posthog.kafka_client.topics import KAFKA_HOG_INVOCATION_RESULTS

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

KAFKA_HOG_INVOCATION_RESULTS_TABLE = f"kafka_{HOG_INVOCATION_RESULTS_TABLE}"

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
