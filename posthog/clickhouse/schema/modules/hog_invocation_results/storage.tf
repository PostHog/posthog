# Tables that hold data, and the materialized views between them.

module "hog_invocation_results_data" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "hog_invocation_results_data")
  database     = var.database
  name         = "hog_invocation_results_data"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.hog_invocation_results_data${var.zk_path_suffix}', '{replica}-{shard}', version)"
  partition_by = "toYYYYMMDD(scheduled_at)"
  order_by     = "(team_id, function_kind, function_id, invocation_id)"
  ttl          = var.ttl ? "toDate(scheduled_at) + toIntervalDay(30)" : null
  settings     = "index_granularity = 1024, ttl_only_drop_parts = 1"
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "function_kind", type = "LowCardinality(String)" },
    { name = "function_id", type = "String" },
    { name = "invocation_id", type = "String" },
    { name = "parent_run_id", type = "String" },
    { name = "status", type = "LowCardinality(String)" },
    { name = "attempts", type = "UInt8" },
    { name = "is_retry", type = "UInt8" },
    { name = "scheduled_at", type = "DateTime64(6, 'UTC')" },
    { name = "first_scheduled_at", type = "DateTime64(6, 'UTC')", default_expression = "scheduled_at" },
    { name = "started_at", type = "Nullable(DateTime64(6, 'UTC'))" },
    { name = "finished_at", type = "Nullable(DateTime64(6, 'UTC'))" },
    { name = "duration_ms", type = "Nullable(UInt32)" },
    { name = "error_kind", type = "LowCardinality(String)" },
    { name = "error_message", type = "String" },
    { name = "event_uuid", type = "String" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "String" },
    { name = "invocation_globals", type = "String" },
    { name = "version", type = "UInt64" },
    { name = "is_deleted", type = "UInt8", default_expression = "0" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
  indexes = [
    { name = "status_idx", expression = "status", type = "set(8)", granularity = 1 },
    { name = "function_idx", expression = "function_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "event_uuid_idx", expression = "event_uuid", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "is_retry_idx", expression = "is_retry", type = "set(2)", granularity = 1 },
  ]
  override = try(var.overrides["hog_invocation_results_data"], {})
}
