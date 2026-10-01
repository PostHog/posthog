# Distributed tables, views and dictionaries that queries read from.

module "app_metrics" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "app_metrics")
  database = var.database
  name     = "app_metrics"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_app_metrics', rand())"
  columns  = local.sharded_app_metrics_columns
  override = try(var.overrides["app_metrics"], {})
}

module "app_metrics2" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "app_metrics2")
  database = var.database
  name     = "app_metrics2"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_app_metrics2', rand())"
  columns  = local.sharded_app_metrics2_columns
  override = try(var.overrides["app_metrics2"], {})
}
