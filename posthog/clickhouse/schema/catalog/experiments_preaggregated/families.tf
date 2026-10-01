module "sharded_experiment_exposures_preaggregated_family" {
  source = "../../lib/table_family"

  name     = "experiment_exposures_preaggregated"
  database = var.database
  columns  = local.sharded_experiment_exposures_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, entity_id, breakdown_value)"
    ttl          = var.ttl ? "expires_at" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    write = false
  }
  sharding_key = "cityHash64(entity_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.experiment_exposures_preaggregated"
    cluster     = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_experiment_exposures_preaggregated", "experiment_exposures_preaggregated"], name) }
  })
}

module "sharded_experiment_metric_events_preaggregated_family" {
  source = "../../lib/table_family"

  name     = "experiment_metric_events_preaggregated"
  database = var.database
  layout   = "global"
  columns  = local.sharded_experiment_metric_events_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, entity_id, timestamp, event_uuid)"
    ttl          = var.ttl ? "expires_at" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    read = true
  }
  sharding_key = "cityHash64(entity_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.experiment_metric_events_preaggregated"
    cluster     = "aux"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_experiment_metric_events_preaggregated", "experiment_metric_events_preaggregated"], name) }
  })
  names = { storage = "sharded_experiment_metric_events_preaggregated" }
}
