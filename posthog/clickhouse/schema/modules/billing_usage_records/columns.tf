# Column lists that more than one object uses.

locals {
  kafka_billing_usage_records_columns = [
    { name = "schema_version", type = "UInt8" },
    { name = "record_id", type = "String" },
    { name = "producer_id", type = "LowCardinality(String)" },
    { name = "team_id", type = "Int64" },
    { name = "organization_id", type = "UUID" },
    { name = "usage_key", type = "LowCardinality(String)" },
    { name = "unit", type = "LowCardinality(String)" },
    { name = "quantity", type = "Int64" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "inserted_at", type = "DateTime64(6, 'UTC')" },
  ]

  sharded_billing_usage_records_columns = concat(local.kafka_billing_usage_records_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])
}
