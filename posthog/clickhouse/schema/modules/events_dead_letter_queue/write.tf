# Distributed tables that inserts go through.

module "writable_events_dead_letter_queue" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_events_dead_letter_queue")
  database = var.database
  name     = "writable_events_dead_letter_queue"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'events_dead_letter_queue')"
  columns  = local.events_dead_letter_queue_columns
  override = try(var.overrides["writable_events_dead_letter_queue"], {})
}
