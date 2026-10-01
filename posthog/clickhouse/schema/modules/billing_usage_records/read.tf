# Distributed tables, views and dictionaries that queries read from.

module "billing_usage_records" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "billing_usage_records")
  database = var.database
  name     = "billing_usage_records"
  engine   = "Distributed('aux', '${var.database}', 'sharded_billing_usage_records', cityHash64(team_id))"
  columns  = local.sharded_billing_usage_records_columns
  override = try(var.overrides["billing_usage_records"], {})
}
