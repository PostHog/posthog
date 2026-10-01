# Distributed tables that inserts go through.

module "writable_heatmaps" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_heatmaps")
  database = var.database
  name     = "writable_heatmaps"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_heatmaps', cityHash64(concat(toString(team_id), '-', session_id, '-', toString(toDate(timestamp)))))"
  columns  = local.sharded_heatmaps_columns
  override = try(var.overrides["writable_heatmaps"], {})
}
