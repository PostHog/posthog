# Tables that hold data, and the materialized views between them.

module "plugin_log_entries" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "plugin_log_entries")
  database     = var.database
  name         = "plugin_log_entries"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.plugin_log_entries${var.zk_path_suffix}', '{replica}-{shard}', _timestamp)"
  partition_by = "toYYYYMMDD(timestamp)"
  order_by     = "(team_id, plugin_id, plugin_config_id, timestamp)"
  ttl          = var.ttl ? "toDate(timestamp) + toIntervalWeek(1)" : null
  settings     = "index_granularity = 512"
  columns      = local.plugin_log_entries_columns
  override     = try(var.overrides["plugin_log_entries"], {})
}
