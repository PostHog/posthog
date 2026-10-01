# Kafka tables and the materialized views that consume them.

module "events_dead_letter_queue_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "events_dead_letter_queue_mv")
  database = var.database
  name     = "events_dead_letter_queue_mv"
  to_table = "${var.database}.writable_events_dead_letter_queue"
  query    = <<-SQL
    SELECT
        id,
        event_uuid,
        event,
        properties,
        distinct_id,
        team_id,
        elements_chain,
        created_at,
        ip,
        site_url,
        now,
        raw_payload,
        error_timestamp,
        error_location,
        error,
        tags,
        _timestamp,
        _offset
    FROM ${var.database}.kafka_events_dead_letter_queue
  SQL
  override = try(var.overrides["events_dead_letter_queue_mv"], {})

  depends_on = [
    module.kafka_events_dead_letter_queue,
    module.writable_events_dead_letter_queue,
  ]
}

module "kafka_events_dead_letter_queue" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_events_dead_letter_queue")
  database = var.database
  name     = "kafka_events_dead_letter_queue"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_skip_broken_messages = 1000, kafka_topic_list = 'events_dead_letter_queue'"
  columns  = local.kafka_events_dead_letter_queue_columns
  override = try(var.overrides["kafka_events_dead_letter_queue"], {})
}
