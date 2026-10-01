# Distributed tables that inserts go through.

module "writable_flag_evaluations" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_flag_evaluations")
  database = var.database
  name     = "writable_flag_evaluations"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_flag_evaluations', sipHash64(distinct_id))"
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "LowCardinality(String)" },
    { name = "properties", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')" },
    { name = "person_id", type = "UUID" },
    { name = "inserted_at", type = "DateTime64(6, 'UTC')", default_expression = "timestamp" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
  override = try(var.overrides["writable_flag_evaluations"], {})
}
