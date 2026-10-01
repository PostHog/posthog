# Distributed tables, views and dictionaries that queries read from.

module "query_log_archive" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "query_log_archive")
  database = var.database
  name     = "query_log_archive"
  engine   = "Distributed('ops', '${var.database}', 'sharded_query_log_archive')"
  columns  = local.sharded_query_log_archive_columns
  override = try(var.overrides["query_log_archive"], {})
}
