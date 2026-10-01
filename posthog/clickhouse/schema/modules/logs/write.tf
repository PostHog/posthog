# Distributed tables that inserts go through.

module "writable_logs34" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_logs34")
  database = var.database
  name     = "writable_logs34"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'logs34')"
  settings = "background_insert_batch = 1"
  columns  = local.logs34_columns
  override = try(var.overrides["writable_logs34"], {})
}
