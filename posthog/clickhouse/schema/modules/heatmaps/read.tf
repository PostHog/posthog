# Distributed tables, views and dictionaries that queries read from.

module "heatmaps" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "heatmaps")
  database = var.database
  name     = "heatmaps"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_heatmaps', cityHash64(concat(toString(team_id), '-', session_id, '-', toString(toDate(timestamp)))))"
  columns  = local.sharded_heatmaps_columns
  override = try(var.overrides["heatmaps"], {})
}
