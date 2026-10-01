# Distributed tables, views and dictionaries that queries read from.

module "log_entries" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "log_entries")
  database = var.database
  name     = "log_entries"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_log_entries', rand())"
  columns  = local.log_entries_data_columns
  override = try(var.overrides["log_entries"], {})
}

module "log_entries_distributed" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "log_entries_distributed")
  database = var.database
  name     = "log_entries_distributed"
  engine   = "Distributed('aux', '${var.database}', 'log_entries_data')"
  columns  = local.log_entries_data_columns
  override = try(var.overrides["log_entries_distributed"], {})
}
