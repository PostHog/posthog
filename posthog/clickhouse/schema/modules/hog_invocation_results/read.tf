# Distributed tables, views and dictionaries that queries read from.

module "hog_invocation_results" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "hog_invocation_results")
  database = var.database
  name     = "hog_invocation_results"
  engine   = "Distributed('aux', '${var.database}', 'hog_invocation_results_data')"
  columns = concat(local.kafka_hog_invocation_results_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])
  override = try(var.overrides["hog_invocation_results"], {})
}
