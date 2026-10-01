# Distributed tables that inserts go through.

module "writable_app_metrics" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_app_metrics")
  database = var.database
  name     = "writable_app_metrics"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_app_metrics', rand())"
  columns  = local.sharded_app_metrics_columns
  override = try(var.overrides["writable_app_metrics"], {})
}

module "writable_app_metrics2" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_app_metrics2")
  database = var.database
  name     = "writable_app_metrics2"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_app_metrics2', rand())"
  columns  = local.sharded_app_metrics2_columns
  override = try(var.overrides["writable_app_metrics2"], {})
}
