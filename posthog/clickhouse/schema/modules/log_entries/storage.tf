# Tables that hold data, and the materialized views between them.

module "log_entries_data" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "log_entries_data")
  database     = var.database
  name         = "log_entries_data"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.log_entries_data${var.zk_path_suffix}', '{replica}', _timestamp)"
  partition_by = "toYYYYMMDD(timestamp)"
  order_by     = "(team_id, log_source, log_source_id, instance_id, timestamp)"
  ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(90)" : null
  settings     = "index_granularity = 1024, ttl_only_drop_parts = 1"
  columns      = local.log_entries_data_columns
  override     = try(var.overrides["log_entries_data"], {})
}

module "sharded_log_entries" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_log_entries")
  database     = var.database
  name         = "sharded_log_entries"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_log_entries${var.zk_path_suffix}', '{replica}', _timestamp)"
  partition_by = "toYYYYMMDD(timestamp)"
  order_by     = "(team_id, log_source, log_source_id, instance_id, timestamp)"
  ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(90)" : null
  settings     = "index_granularity = 1024, ttl_only_drop_parts = 1"
  columns      = local.log_entries_data_columns
  override     = try(var.overrides["sharded_log_entries"], {})
}
