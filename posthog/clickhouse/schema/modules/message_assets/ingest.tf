# Kafka tables and the materialized views that consume them.

module "kafka_message_assets" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_message_assets")
  database = var.database
  name     = "kafka_message_assets"
  engine   = "Kafka(warpstream_cyclotron)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_message_assets', kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_message_assets'"
  columns  = local.kafka_message_assets_columns
  override = try(var.overrides["kafka_message_assets"], {})
}

module "message_assets_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "message_assets_mv")
  database = var.database
  name     = "message_assets_mv"
  to_table = "${var.database}.message_assets_data"
  query    = <<-SQL
    SELECT
        team_id,
        function_kind,
        function_id,
        parent_run_id,
        invocation_id,
        action_id,
        kind,
        distinct_id,
        person_id,
        recipient,
        subject,
        status,
        sent_at,
        version,
        is_deleted,
        html,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_message_assets
  SQL
  override = try(var.overrides["message_assets_mv"], {})

  depends_on = [
    module.kafka_message_assets,
    module.message_assets_data,
  ]
}
