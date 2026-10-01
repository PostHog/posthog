# Kafka tables and the materialized views that consume them.

module "kafka_person" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_person")
  database = var.database
  name     = "kafka_person"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'clickhouse_person'"
  columns  = local.kafka_person_columns
  override = try(var.overrides["kafka_person"], {})
}

module "person_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "person_mv")
  database = var.database
  name     = "person_mv"
  to_table = "${var.database}.writable_person"
  query    = <<-SQL
    SELECT
        id,
        created_at,
        team_id,
        properties,
        is_identified,
        is_deleted,
        version,
        last_seen_at,
        _timestamp,
        _offset
    FROM ${var.database}.kafka_person
  SQL
  override = try(var.overrides["person_mv"], {})

  depends_on = [
    module.kafka_person,
    module.writable_person,
  ]
}
