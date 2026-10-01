# Column lists that more than one object uses.

locals {
  sharded_distinct_id_usage_columns = [
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "minute", type = "DateTime" },
    { name = "event_count", type = "UInt64" },
  ]
}
