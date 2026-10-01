# Tables that hold data, and the materialized views between them.

module "sharded_platform_alert_events" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_platform_alert_events")
  database     = var.database
  name         = "sharded_platform_alert_events"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.platform_alert_events${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toYYYYMM(occurred_at)"
  primary_key  = "(team_id, configuration_id, alert_id, occurred_at)"
  order_by     = "(team_id, configuration_id, alert_id, occurred_at, evaluation_key)"
  ttl          = var.ttl ? "expires_at" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_platform_alert_events_columns
  override     = try(var.overrides["sharded_platform_alert_events"], {})
}
