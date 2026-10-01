# Kafka tables and the materialized views that consume them.


module "kafka_tophog_ws" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(local.deployment.exclude, "kafka_tophog_ws")
  database = var.database
  name     = "kafka_tophog_ws"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "date_time_input_format = 'best_effort', kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_tophog_ws', kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_tophog'"
  columns  = local.kafka_tophog_columns
  override = try(local.deployment.overrides["kafka_tophog_ws"], {})
}


module "tophog_ws_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(local.deployment.exclude, "tophog_ws_mv")
  database = var.database
  name     = "tophog_ws_mv"
  to_table = "${var.database}.writable_tophog"
  query    = <<-SQL
    SELECT
        timestamp,
        metric,
        type,
        key,
        value,
        count,
        pipeline,
        lane,
        labels
    FROM ${var.database}.kafka_tophog_ws
  SQL
  override = try(local.deployment.overrides["tophog_ws_mv"], {})

  depends_on = [
    module.kafka_tophog_ws,
    module.sharded_tophog_family,
  ]
}
