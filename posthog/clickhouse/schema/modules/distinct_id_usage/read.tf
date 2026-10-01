# Distributed tables, views and dictionaries that queries read from.

module "distinct_id_usage" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "distinct_id_usage")
  database = var.database
  name     = "distinct_id_usage"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_distinct_id_usage', sipHash64(distinct_id))"
  columns  = local.sharded_distinct_id_usage_columns
  override = try(var.overrides["distinct_id_usage"], {})
}
