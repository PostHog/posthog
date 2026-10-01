# Tables that hold data, and the materialized views between them.

module "message_assets_data" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "message_assets_data")
  database     = var.database
  name         = "message_assets_data"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.message_assets_data${var.zk_path_suffix}', '{replica}-{shard}', version)"
  partition_by = "toYYYYMMDD(sent_at)"
  order_by     = "(team_id, function_kind, function_id, invocation_id, action_id)"
  ttl          = var.ttl ? "toDate(sent_at) + toIntervalDay(30)" : null
  settings     = "index_granularity = 1024, ttl_only_drop_parts = 1"
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "function_kind", type = "LowCardinality(String)" },
    { name = "function_id", type = "String" },
    { name = "parent_run_id", type = "String" },
    { name = "invocation_id", type = "String" },
    { name = "action_id", type = "String" },
    { name = "kind", type = "LowCardinality(String)" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "String" },
    { name = "recipient", type = "String" },
    { name = "subject", type = "String" },
    { name = "status", type = "LowCardinality(String)" },
    { name = "sent_at", type = "DateTime64(6, 'UTC')" },
    { name = "version", type = "UInt64" },
    { name = "is_deleted", type = "UInt8", default_expression = "0" },
    { name = "html", type = "String", codec = "ZSTD(3)" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
  indexes = [
    { name = "parent_run_idx", expression = "parent_run_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "distinct_id_idx", expression = "distinct_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "person_id_idx", expression = "person_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "recipient_idx", expression = "recipient", type = "bloom_filter(0.01)", granularity = 1 },
  ]
  override = try(var.overrides["message_assets_data"], {})
}
