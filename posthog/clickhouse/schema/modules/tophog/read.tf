# Distributed tables, views and dictionaries that queries read from.

module "tophog" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "tophog")
  database = var.database
  name     = "tophog"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_tophog', cityHash64(toString(key)))"
  columns  = local.sharded_tophog_columns
  override = try(var.overrides["tophog"], {})
}
