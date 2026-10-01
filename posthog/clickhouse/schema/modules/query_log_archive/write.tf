# Distributed tables that inserts go through.

module "writable_query_log_archive" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_query_log_archive")
  database = var.database
  name     = "writable_query_log_archive"
  engine   = "Distributed('ops', '${var.database}', 'query_log_archive_buffer')"
  columns  = local.query_log_archive_buffer_columns
  override = try(var.overrides["writable_query_log_archive"], {})
}
