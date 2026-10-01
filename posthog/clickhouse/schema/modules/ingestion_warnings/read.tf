# Distributed tables, views and dictionaries that queries read from.

module "ingestion_warnings" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "ingestion_warnings")
  database = var.database
  name     = "ingestion_warnings"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_ingestion_warnings', rand())"
  columns  = local.sharded_ingestion_warnings_columns
  override = try(var.overrides["ingestion_warnings"], {})
}

module "ingestion_warnings_v2_distributed" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "ingestion_warnings_v2_distributed")
  database = var.database
  name     = "ingestion_warnings_v2_distributed"
  engine   = "Distributed('aux', '${var.database}', 'ingestion_warnings_v2')"
  columns  = local.ingestion_warnings_v2_columns
  override = try(var.overrides["ingestion_warnings_v2_distributed"], {})
}
