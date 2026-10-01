# Column lists that more than one object uses.

locals {
  kafka_groups_columns = [
    { name = "group_type_index", type = "UInt8" },
    { name = "group_key", type = "String" },
    { name = "created_at", type = "DateTime64(3)" },
    { name = "team_id", type = "Int64" },
    { name = "group_properties", type = "String" },
  ]

  writable_groups_columns = concat(local.kafka_groups_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ])
}
