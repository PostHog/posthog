# Distributed tables that inserts go through.

module "writable_tophog" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_tophog")
  database = var.database
  name     = "writable_tophog"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_tophog', cityHash64(toString(key)))"
  columns  = local.sharded_tophog_columns
  override = try(var.overrides["writable_tophog"], {})
}
