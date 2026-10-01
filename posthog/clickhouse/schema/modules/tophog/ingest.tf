# Kafka tables and the materialized views that consume them.

module "kafka_tophog" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_tophog")
  database = var.database
  name     = "kafka_tophog"
  engine   = "Kafka(msk_cluster)"
  settings = "date_time_input_format = 'best_effort', kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_tophog', kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_tophog'"
  columns  = local.kafka_tophog_columns
  override = try(var.overrides["kafka_tophog"], {})
}

module "kafka_tophog_ws" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_tophog_ws")
  database = var.database
  name     = "kafka_tophog_ws"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "date_time_input_format = 'best_effort', kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_tophog_ws', kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_tophog'"
  columns  = local.kafka_tophog_columns
  override = try(var.overrides["kafka_tophog_ws"], {})
}

module "tophog_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "tophog_mv")
  database = var.database
  name     = "tophog_mv"
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
    FROM ${var.database}.kafka_tophog
  SQL
  override = try(var.overrides["tophog_mv"], {})

  depends_on = [
    module.kafka_tophog,
    module.writable_tophog,
  ]
}

module "tophog_ws_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "tophog_ws_mv")
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
  override = try(var.overrides["tophog_ws_mv"], {})

  depends_on = [
    module.kafka_tophog_ws,
    module.writable_tophog,
  ]
}
