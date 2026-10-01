# Tables that hold data, and the materialized views between them.

module "sharded_distinct_id_usage" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_distinct_id_usage")
  database     = var.database
  name         = "sharded_distinct_id_usage"
  engine       = "ReplicatedSummingMergeTree('/clickhouse/tables/{shard}/posthog.distinct_id_usage${var.zk_path_suffix}', '{replica}', (event_count))"
  partition_by = "toYYYYMMDD(minute)"
  order_by     = "(team_id, minute, distinct_id)"
  ttl          = var.ttl ? "toDate(minute) + toIntervalDay(7)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_distinct_id_usage_columns
  override     = try(var.overrides["sharded_distinct_id_usage"], {})
}
