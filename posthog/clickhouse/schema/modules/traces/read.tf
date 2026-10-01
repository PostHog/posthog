# Distributed tables, views and dictionaries that queries read from.

module "trace_attributes_distributed" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "trace_attributes_distributed")
  database = var.database
  name     = "trace_attributes_distributed"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'trace_attributes')"
  columns  = local.trace_attributes_columns
  override = try(var.overrides["trace_attributes_distributed"], {})
}

module "trace_spans_distributed" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "trace_spans_distributed")
  database = var.database
  name     = "trace_spans_distributed"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'trace_spans')"
  columns  = local.trace_spans_columns
  override = try(var.overrides["trace_spans_distributed"], {})
}
