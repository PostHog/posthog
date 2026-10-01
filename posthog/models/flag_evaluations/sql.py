from django.conf import settings

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_FLAG_EVALUATIONS, kafka_engine
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_FLAG_EVALUATIONS

# Flag evaluation telemetry ($feature_flag_called events routed out of the events
# table). The column set is the events table's, narrowed to what a flag evaluation
# actually carries: no elements_chain, no person_mode, and no person or group
# property blobs, since no Insight or Hog function breaks down or filters on them.
# It keeps the full properties JSON as the source of truth, so queries and
# integrations built on event properties survive the routing switch. The 90-day
# TTL is what makes rows that wide affordable.
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

FLAG_EVALUATIONS_TTL_DAYS = 90

# The only event this table stores. posthog/models/deletion_targets.py uses it to skip this table
# for deletion requests that name other events, so a producer writing a second event name here has
# to update the target's stored_events.
FLAG_EVALUATIONS_SOURCE_EVENT = "$feature_flag_called"

KAFKA_FLAG_EVALUATIONS_TABLE = f"kafka_{FLAG_EVALUATIONS_TABLE}"

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
    inserted_at DateTime64(6, 'UTC'){ts_default}
""".strip()

FLAG_EVALUATIONS_KAFKA_COLUMNS = _FLAG_EVALUATIONS_COLUMNS_TEMPLATE.format(ts_default="")

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
-- The block and batch sizes are an order of magnitude below the precalculated
-- Kafka tables on this role: each row carries the full event-properties JSON, so
-- large blocks cost far more memory. The 10s poll timeout is deliberate: it is
-- in the range the other WarpStream consumers use, not the 1s the precalculated
-- tables set.
SETTINGS
    kafka_max_block_size = 10000,
    kafka_poll_max_batch_size = 10000,
    kafka_poll_timeout_ms = 10000,
    kafka_flush_interval_ms = 7500,
    kafka_num_consumers = 1,
    kafka_skip_broken_messages = 100
"""
)
