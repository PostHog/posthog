# Column lists that more than one object uses.

locals {
  kafka_precalculated_person_properties_columns = [
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "UUID" },
    { name = "condition", type = "String" },
    { name = "matches", type = "Bool" },
    { name = "source", type = "String" },
  ]

  sharded_precalculated_person_properties_columns = concat(local.kafka_precalculated_person_properties_columns, [
    { name = "_timestamp", type = "DateTime64(6)" },
    { name = "_offset", type = "UInt64" },
  ])

  sharded_precalculated_events_columns = [
    { name = "team_id", type = "Int64" },
    { name = "date", type = "Date" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "UUID" },
    { name = "condition", type = "String" },
    { name = "uuid", type = "UUID" },
    { name = "source", type = "String" },
    { name = "_timestamp", type = "DateTime64(6)" },
    { name = "_partition", type = "UInt64" },
    { name = "_offset", type = "UInt64" },
  ]
}
