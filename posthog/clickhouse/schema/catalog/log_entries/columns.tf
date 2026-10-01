# Column lists that more than one object uses.

locals {
  kafka_log_entries_v3_columns = [
    { name = "team_id", type = "UInt64" },
    { name = "log_source", type = "LowCardinality(String)" },
    { name = "log_source_id", type = "String" },
    { name = "instance_id", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "level", type = "LowCardinality(String)" },
    { name = "message", type = "String" },
  ]

  log_entries_data_columns = concat(local.kafka_log_entries_v3_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ])
}
