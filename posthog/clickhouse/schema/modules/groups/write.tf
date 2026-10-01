# Distributed tables that inserts go through.

module "writable_groups" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_groups")
  database = var.database
  name     = "writable_groups"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'groups')"
  columns  = local.writable_groups_columns
  override = try(var.overrides["writable_groups"], {})
}
