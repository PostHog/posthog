# Kafka tables and the materialized views that consume them.

module "billing_usage_records_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "billing_usage_records_mv")
  database = var.database
  name     = "billing_usage_records_mv"
  to_table = "${var.database}.writable_billing_usage_records"
  query    = <<-SQL
    SELECT
        schema_version,
        record_id,
        producer_id,
        team_id,
        organization_id,
        usage_key,
        unit,
        quantity,
        timestamp,
        inserted_at,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_billing_usage_records
  SQL
  override = try(var.overrides["billing_usage_records_mv"], {})

  depends_on = [
    module.kafka_billing_usage_records,
    module.writable_billing_usage_records,
  ]
}

module "kafka_billing_usage_records" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_billing_usage_records")
  database = var.database
  name     = "kafka_billing_usage_records"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "date_time_input_format = 'best_effort', kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_billing_usage_records', kafka_topic_list = 'clickhouse_billing_usage_records'"
  columns  = local.kafka_billing_usage_records_columns
  override = try(var.overrides["kafka_billing_usage_records"], {})
}
