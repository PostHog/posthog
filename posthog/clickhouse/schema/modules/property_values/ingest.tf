# Kafka tables and the materialized views that consume them.

module "kafka_property_values" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_property_values")
  database = var.database
  name     = "kafka_property_values"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_property_values', kafka_num_consumers = 1, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_property_values'"
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "property_type", type = "LowCardinality(String)" },
    { name = "property_key", type = "String" },
    { name = "property_value", type = "String" },
    { name = "property_count", type = "UInt64" },
  ]
  override = try(var.overrides["kafka_property_values"], {})
}

module "property_values_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "property_values_mv")
  database = var.database
  name     = "property_values_mv"
  to_table = "${var.database}.property_values"
  query    = <<-SQL
    SELECT
        team_id,
        property_type,
        property_key,
        property_value,
        property_count,
        coalesce(_timestamp, now()) AS last_seen
    FROM ${var.database}.kafka_property_values
  SQL
  override = try(var.overrides["property_values_mv"], {})

  depends_on = [
    module.kafka_property_values,
    module.property_values,
  ]
}
