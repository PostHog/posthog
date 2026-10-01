# Tables that hold data, and the materialized views between them.

module "sharded_ai_events" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_ai_events")
  database     = var.database
  name         = "sharded_ai_events"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/{shard}/posthog.ai_events${var.zk_path_suffix}', '{replica}')"
  partition_by = "toYYYYMM(drop_date)"
  order_by     = "(team_id, trace_id, timestamp)"
  ttl          = var.ttl ? "drop_date" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_ai_events_columns
  indexes = [
    { name = "idx_trace_id", expression = "trace_id", type = "bloom_filter(0.001)", granularity = 1 },
    { name = "idx_session_id", expression = "session_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_parent_id", expression = "parent_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_span_id", expression = "span_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_prompt_name", expression = "prompt_name", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_model", expression = "model", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_experiment_id", expression = "experiment_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_event", expression = "event", type = "set(20)", granularity = 1 },
    { name = "idx_is_error", expression = "is_error", type = "set(2)", granularity = 1 },
    { name = "idx_provider", expression = "provider", type = "set(50)", granularity = 1 },
  ]
  override = try(var.overrides["sharded_ai_events"], {})
}
