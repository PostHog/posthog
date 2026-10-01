# Column lists that more than one object uses.

locals {
  kafka_person_distinct_id_overrides_columns = [
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "UUID" },
    { name = "is_deleted", type = "Int8" },
    { name = "version", type = "Int64" },
  ]

  person_distinct_id_overrides_columns = concat(local.kafka_person_distinct_id_overrides_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])
}
