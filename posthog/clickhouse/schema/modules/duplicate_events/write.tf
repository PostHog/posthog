# Distributed tables that inserts go through.

module "writable_duplicate_events" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_duplicate_events")
  database = var.database
  name     = "writable_duplicate_events"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'duplicate_events')"
  columns  = local.duplicate_events_columns
  override = try(var.overrides["writable_duplicate_events"], {})
}
