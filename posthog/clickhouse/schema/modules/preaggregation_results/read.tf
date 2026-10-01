# Distributed tables, views and dictionaries that queries read from.

module "preaggregation_results" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "preaggregation_results")
  database = var.database
  name     = "preaggregation_results"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_preaggregation_results', sipHash64(job_id))"
  columns  = local.sharded_preaggregation_results_columns
  override = try(var.overrides["preaggregation_results"], {})
}
