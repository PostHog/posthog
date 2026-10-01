# Column lists that more than one object uses.

locals {
  kafka_message_assets_columns = [
    { name = "team_id", type = "Int64" },
    { name = "function_kind", type = "LowCardinality(String)" },
    { name = "function_id", type = "String" },
    { name = "parent_run_id", type = "String" },
    { name = "invocation_id", type = "String" },
    { name = "action_id", type = "String" },
    { name = "kind", type = "LowCardinality(String)" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "String" },
    { name = "recipient", type = "String" },
    { name = "subject", type = "String" },
    { name = "status", type = "LowCardinality(String)" },
    { name = "sent_at", type = "DateTime64(6, 'UTC')" },
    { name = "version", type = "UInt64" },
    { name = "is_deleted", type = "UInt8" },
    { name = "html", type = "String" },
  ]
}
