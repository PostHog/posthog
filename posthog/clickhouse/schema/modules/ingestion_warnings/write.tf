# Distributed tables that inserts go through.

module "writable_ingestion_warnings" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_ingestion_warnings")
  database = var.database
  name     = "writable_ingestion_warnings"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_ingestion_warnings', rand())"
  columns  = local.sharded_ingestion_warnings_columns
  override = try(var.overrides["writable_ingestion_warnings"], {})
}
