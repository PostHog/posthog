# Distributed tables that inserts go through.

module "writable_distinct_id_usage" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_distinct_id_usage")
  database = var.database
  name     = "writable_distinct_id_usage"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_distinct_id_usage', sipHash64(distinct_id))"
  columns  = local.sharded_distinct_id_usage_columns
  override = try(var.overrides["writable_distinct_id_usage"], {})
}
