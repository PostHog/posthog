# local-single deltas to the ingestion-events objects.
database "posthog" {
  # The single-node stack has no `logs` remote_servers entry — every role lives on this
  # one server, so the Distributed front reaches logs34 through the self-pointing
  # posthog_single_shard cluster. CLICKHOUSE_LOGS_WRITE_CLUSTER falls back to that there.
  patch_table "writable_logs34" {
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "logs34"
    }
  }
}
