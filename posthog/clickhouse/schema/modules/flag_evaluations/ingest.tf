# Kafka tables and the materialized views that consume them.

module "flag_evaluations_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "flag_evaluations_mv")
  database = var.database
  name     = "flag_evaluations_mv"
  to_table = "${var.database}.writable_flag_evaluations"
  query    = <<-SQL
    SELECT
        uuid,
        event,
        properties,
        timestamp,
        team_id,
        distinct_id,
        created_at,
        person_id,
        if(inserted_at = toDateTime64('1970-01-01 00:00:00', 6, 'UTC'), _timestamp, inserted_at) AS inserted_at,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_flag_evaluations
  SQL
  override = try(var.overrides["flag_evaluations_mv"], {})

  depends_on = [
    module.kafka_flag_evaluations,
    module.writable_flag_evaluations,
  ]
}

module "kafka_flag_evaluations" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_flag_evaluations")
  database = var.database
  name     = "kafka_flag_evaluations"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "kafka_flush_interval_ms = 7500, kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_flag_evaluations', kafka_max_block_size = 10000, kafka_num_consumers = 1, kafka_poll_max_batch_size = 10000, kafka_poll_timeout_ms = 10000, kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_flag_evaluations'"
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "LowCardinality(String)" },
    { name = "properties", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')" },
    { name = "person_id", type = "UUID" },
    { name = "inserted_at", type = "DateTime64(6, 'UTC')" },
  ]
  override = try(var.overrides["kafka_flag_evaluations"], {})
}
