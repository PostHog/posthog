# Kafka tables and the materialized views that consume them.

module "events_json_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "events_json_mv")
  database = var.database
  name     = "events_json_mv"
  to_table = "${var.database}.writable_events"
  query    = <<-SQL
    SELECT
        uuid,
        event,
        properties,
        timestamp,
        team_id,
        distinct_id,
        elements_chain,
        created_at,
        person_id,
        person_created_at,
        person_properties,
        group0_properties,
        group1_properties,
        group2_properties,
        group3_properties,
        group4_properties,
        group0_created_at,
        group1_created_at,
        group2_created_at,
        group3_created_at,
        group4_created_at,
        person_mode,
        historical_migration,
        dmat_string_0,
        dmat_string_1,
        dmat_string_2,
        dmat_string_3,
        dmat_string_4,
        dmat_string_5,
        dmat_string_6,
        dmat_string_7,
        dmat_string_8,
        dmat_string_9,
        _timestamp,
        _offset,
        arrayMap(i -> (_headers.value[i]), arrayFilter(i -> ((_headers.name[i]) = 'kafka-consumer-breadcrumbs'), arrayEnumerate(_headers.name))) AS consumer_breadcrumbs
    FROM ${var.database}.kafka_events_json
  SQL
  override = try(var.overrides["events_json_mv"], {})

  depends_on = [
    module.kafka_events_json,
    module.writable_events,
  ]
}

module "kafka_events_json" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_events_json")
  database = var.database
  name     = "kafka_events_json"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_events_json'"
  columns  = local.kafka_events_json_columns
  override = try(var.overrides["kafka_events_json"], {})
}
