# Tables that hold data, and the materialized views between them.

module "sharded_experiment_exposures_preaggregated" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_experiment_exposures_preaggregated")
  database     = var.database
  name         = "sharded_experiment_exposures_preaggregated"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.experiment_exposures_preaggregated${var.zk_path_suffix}', '{replica}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, job_id, entity_id, breakdown_value)"
  ttl          = var.ttl ? "expires_at" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_experiment_exposures_preaggregated_columns
  override     = try(var.overrides["sharded_experiment_exposures_preaggregated"], {})
}

module "sharded_experiment_metric_events_preaggregated" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_experiment_metric_events_preaggregated")
  database     = var.database
  name         = "sharded_experiment_metric_events_preaggregated"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.experiment_metric_events_preaggregated${var.zk_path_suffix}', '{replica}-{shard}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, job_id, entity_id, timestamp, event_uuid)"
  ttl          = var.ttl ? "expires_at" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_experiment_metric_events_preaggregated_columns
  override     = try(var.overrides["sharded_experiment_metric_events_preaggregated"], {})
}
