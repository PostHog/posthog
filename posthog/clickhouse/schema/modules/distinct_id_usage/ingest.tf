# Kafka tables and the materialized views that consume them.

module "distinct_id_usage_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "distinct_id_usage_mv")
  database = var.database
  name     = "distinct_id_usage_mv"
  to_table = "${var.database}.writable_distinct_id_usage"
  query    = <<-SQL
    SELECT
        team_id,
        distinct_id,
        toStartOfMinute(timestamp) AS minute,
        1 AS event_count
    FROM ${var.database}.kafka_distinct_id_usage
  SQL
  override = try(var.overrides["distinct_id_usage_mv"], {})

  depends_on = [
    module.kafka_distinct_id_usage,
    module.writable_distinct_id_usage,
  ]
}

module "kafka_distinct_id_usage" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_distinct_id_usage")
  database = var.database
  name     = "kafka_distinct_id_usage"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_distinct_id_usage', kafka_skip_broken_messages = 100, kafka_topic_list = 'distinct_id_usage_events_json'"
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
  ]
  override = try(var.overrides["kafka_distinct_id_usage"], {})
}
