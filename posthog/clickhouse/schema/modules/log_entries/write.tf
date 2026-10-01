# Distributed tables that inserts go through.

module "writable_log_entries" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_log_entries")
  database = var.database
  name     = "writable_log_entries"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_log_entries', rand())"
  columns  = local.log_entries_data_columns
  override = try(var.overrides["writable_log_entries"], {})
}

module "writable_log_entries_aux" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_log_entries_aux")
  database = var.database
  name     = "writable_log_entries_aux"
  engine   = "Distributed('aux', '${var.database}', 'log_entries_data')"
  columns  = local.log_entries_data_columns
  override = try(var.overrides["writable_log_entries_aux"], {})
}
