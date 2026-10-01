# Kafka tables and the materialized views that consume them.

module "kafka_precalculated_events" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_precalculated_events")
  database = var.database
  name     = "kafka_precalculated_events"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_flush_interval_ms = 7500, kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_prefiltered_events', kafka_max_block_size = 1000000, kafka_num_consumers = 1, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_prefiltered_events'"
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "date", type = "Nullable(Date)" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "UUID" },
    { name = "condition", type = "String" },
    { name = "uuid", type = "UUID" },
    { name = "source", type = "String" },
  ]
  override = try(var.overrides["kafka_precalculated_events"], {})
}

module "kafka_precalculated_person_properties" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_precalculated_person_properties")
  database = var.database
  name     = "kafka_precalculated_person_properties"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_flush_interval_ms = 7500, kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_precalculated_person_properties', kafka_max_block_size = 1000000, kafka_num_consumers = 1, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_precalculated_person_properties'"
  columns  = local.kafka_precalculated_person_properties_columns
  override = try(var.overrides["kafka_precalculated_person_properties"], {})
}

module "precalculated_events_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "precalculated_events_mv")
  database = var.database
  name     = "precalculated_events_mv"
  to_table = "${var.database}.writable_precalculated_events"
  query    = <<-SQL
    SELECT
        team_id,
        ifNull(date, toDate(_timestamp)) AS date,
        distinct_id,
        person_id,
        condition,
        uuid,
        source,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_precalculated_events
  SQL
  override = try(var.overrides["precalculated_events_mv"], {})

  depends_on = [
    module.kafka_precalculated_events,
    module.writable_precalculated_events,
  ]
}

module "precalculated_person_properties_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "precalculated_person_properties_mv")
  database = var.database
  name     = "precalculated_person_properties_mv"
  to_table = "${var.database}.writable_precalculated_person_properties"
  query    = <<-SQL
    SELECT
        team_id,
        distinct_id,
        person_id,
        condition,
        matches,
        source,
        _timestamp,
        _offset
    FROM ${var.database}.kafka_precalculated_person_properties
  SQL
  override = try(var.overrides["precalculated_person_properties_mv"], {})

  depends_on = [
    module.kafka_precalculated_person_properties,
    module.writable_precalculated_person_properties,
  ]
}
