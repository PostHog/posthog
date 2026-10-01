# Column lists that more than one object uses.

locals {
  kafka_person_columns = [
    { name = "id", type = "UUID" },
    { name = "created_at", type = "DateTime64(3)" },
    { name = "team_id", type = "Int64" },
    { name = "properties", type = "String" },
    { name = "is_identified", type = "Int8" },
    { name = "is_deleted", type = "Int8" },
    { name = "version", type = "UInt64" },
    { name = "last_seen_at", type = "Nullable(DateTime64(3))" },
  ]

  person_columns = concat(local.kafka_person_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ])
}
