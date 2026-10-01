# Tables that hold data, and the materialized views between them.

module "error_tracking_issue_fingerprint_overrides" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "error_tracking_issue_fingerprint_overrides")
  database = var.database
  name     = "error_tracking_issue_fingerprint_overrides"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.error_tracking_issue_fingerprint_overrides${var.zk_path_suffix}', '{replica}-{shard}', version)"
  order_by = "(team_id, fingerprint)"
  settings = "index_granularity = 512"
  columns  = local.error_tracking_issue_fingerprint_overrides_columns
  indexes = [
    { name = "kafka_timestamp_minmax_error_tracking_issue_fingerprint_overrides", expression = "_timestamp", type = "minmax", granularity = 3 },
  ]
  override = try(var.overrides["error_tracking_issue_fingerprint_overrides"], {})
}

module "raw_error_tracking_fingerprint_issue_state" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "raw_error_tracking_fingerprint_issue_state")
  database = var.database
  name     = "raw_error_tracking_fingerprint_issue_state"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.raw_error_tracking_fingerprint_issue_state${var.zk_path_suffix}', '{replica}-{shard}', version)"
  order_by = "(team_id, fingerprint)"
  settings = "index_granularity = 512"
  columns  = local.raw_error_tracking_fingerprint_issue_state_columns
  indexes = [
    { name = "kafka_timestamp_minmax_raw_error_tracking_fingerprint_issue_state", expression = "_timestamp", type = "minmax", granularity = 3 },
  ]
  override = try(var.overrides["raw_error_tracking_fingerprint_issue_state"], {})
}
