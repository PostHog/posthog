# Distributed tables, views and dictionaries that queries read from.

module "flag_evaluations" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "flag_evaluations")
  database = var.database
  name     = "flag_evaluations"
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
    { name = "$group_0", type = "String", comment = "column_materializer::$group_0" },
    { name = "$group_1", type = "String", comment = "column_materializer::$group_1" },
    { name = "$group_2", type = "String", comment = "column_materializer::$group_2" },
    { name = "$group_3", type = "String", comment = "column_materializer::$group_3" },
    { name = "$group_4", type = "String", comment = "column_materializer::$group_4" },
    { name = "flag_key", type = "String", comment = "column_materializer::properties::$feature_flag" },
    { name = "response", type = "LowCardinality(String)", comment = "column_materializer::properties::$feature_flag_response" },
    { name = "session_id", type = "String", comment = "column_materializer::properties::$session_id" },
    { name = "request_id", type = "String", comment = "column_materializer::properties::$feature_flag_request_id" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
  override = try(var.overrides["flag_evaluations"], {})
}
