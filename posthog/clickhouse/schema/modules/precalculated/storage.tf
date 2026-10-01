# Tables that hold data, and the materialized views between them.

module "sharded_precalculated_events" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_precalculated_events")
  database     = var.database
  name         = "sharded_precalculated_events"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_precalculated_events${var.zk_path_suffix}', '{replica}', _timestamp)"
  partition_by = "toYYYYMM(date)"
  order_by     = "(team_id, condition, date, distinct_id, uuid)"
  columns      = local.sharded_precalculated_events_columns
  override     = try(var.overrides["sharded_precalculated_events"], {})
}

module "sharded_precalculated_person_properties" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "sharded_precalculated_person_properties")
  database = var.database
  name     = "sharded_precalculated_person_properties"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_precalculated_person_properties${var.zk_path_suffix}', '{replica}', _timestamp)"
  order_by = "(team_id, condition, distinct_id)"
  columns  = local.sharded_precalculated_person_properties_columns
  override = try(var.overrides["sharded_precalculated_person_properties"], {})
}
