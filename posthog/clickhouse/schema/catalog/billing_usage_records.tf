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

module "billing_usage_records" {
  source  = "../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "billing_usage_records"
  database = var.database
  columns  = local.sharded_billing_usage_records_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["inserted_at"]
    partition_by = "toYYYYMM(timestamp)"
    order_by     = "(team_id, toDate(timestamp), producer_id, usage_key, record_id)"
  }
  kafka = {
    topic    = "clickhouse_billing_usage_records"
    columns  = local.kafka_billing_usage_records_columns
    settings = { date_time_input_format = "'best_effort'" }
  }
  mv_select  = join(", ", [for column in local.sharded_billing_usage_records_columns : column.name])
  deployment = merge(var.deployment.sharded, try(var.deployment.families.billing_usage_records, {}), { overrides = var.overrides })
}
