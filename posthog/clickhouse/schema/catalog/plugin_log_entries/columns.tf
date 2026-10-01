# Column lists that more than one object uses.

locals {
  kafka_plugin_log_entries_columns = [
    { name = "id", type = "UUID" },
    { name = "team_id", type = "Int64" },
    { name = "plugin_id", type = "Int64" },
    { name = "plugin_config_id", type = "Int64" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "source", type = "String" },
    { name = "type", type = "String" },
    { name = "message", type = "String" },
    { name = "instance_id", type = "UUID" },
  ]

  plugin_log_entries_columns = concat(local.kafka_plugin_log_entries_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ])
}
