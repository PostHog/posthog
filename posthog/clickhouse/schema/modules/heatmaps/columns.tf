# Column lists that more than one object uses.

locals {
  kafka_heatmaps_columns = [
    { name = "session_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "x", type = "Int16" },
    { name = "y", type = "Int16" },
    { name = "scale_factor", type = "Int16" },
    { name = "viewport_width", type = "Int16" },
    { name = "viewport_height", type = "Int16" },
    { name = "pointer_target_fixed", type = "Bool" },
    { name = "current_url", type = "String" },
    { name = "type", type = "LowCardinality(String)" },
  ]

  sharded_heatmaps_columns = concat(local.kafka_heatmaps_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])
}
