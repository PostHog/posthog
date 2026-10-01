# Distributed tables that inserts go through.

module "writable_plugin_log_entries" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_plugin_log_entries")
  database = var.database
  name     = "writable_plugin_log_entries"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'plugin_log_entries')"
  columns  = local.plugin_log_entries_columns
  override = try(var.overrides["writable_plugin_log_entries"], {})
}
