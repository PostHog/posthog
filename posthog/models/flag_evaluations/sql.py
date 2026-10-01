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
