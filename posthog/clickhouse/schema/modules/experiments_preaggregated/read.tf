# Distributed tables, views and dictionaries that queries read from.

module "experiment_exposures_preaggregated" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "experiment_exposures_preaggregated")
  database = var.database
  name     = "experiment_exposures_preaggregated"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_experiment_exposures_preaggregated', cityHash64(entity_id))"
  columns  = local.sharded_experiment_exposures_preaggregated_columns
  override = try(var.overrides["experiment_exposures_preaggregated"], {})
}

module "experiment_metric_events_preaggregated" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "experiment_metric_events_preaggregated")
  database = var.database
  name     = "experiment_metric_events_preaggregated"
  engine   = "Distributed('aux', '${var.database}', 'sharded_experiment_metric_events_preaggregated', cityHash64(entity_id))"
  columns  = local.sharded_experiment_metric_events_preaggregated_columns
  override = try(var.overrides["experiment_metric_events_preaggregated"], {})
}
