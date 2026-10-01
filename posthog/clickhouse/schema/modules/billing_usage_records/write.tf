# Distributed tables that inserts go through.

module "writable_billing_usage_records" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_billing_usage_records")
  database = var.database
  name     = "writable_billing_usage_records"
  engine   = "Distributed('aux', '${var.database}', 'sharded_billing_usage_records', cityHash64(team_id))"
  columns  = local.sharded_billing_usage_records_columns
  override = try(var.overrides["writable_billing_usage_records"], {})
}
