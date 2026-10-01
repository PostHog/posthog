# Kafka tables and the materialized views that consume them.

module "kafka_person_overrides" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_person_overrides")
  database = var.database
  name     = "kafka_person_overrides"
  engine   = "Kafka"
  settings = "kafka_broker_list = 'kafka:9092', kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse-person-overrides', kafka_topic_list = 'clickhouse_person_override'"
  columns = [
    { name = "team_id", type = "Int32" },
    { name = "old_person_id", type = "UUID" },
    { name = "override_person_id", type = "UUID" },
    { name = "merged_at", type = "DateTime64(6, 'UTC')" },
    { name = "oldest_event", type = "DateTime64(6, 'UTC')" },
    { name = "version", type = "Int32" },
  ]
  override = try(var.overrides["kafka_person_overrides"], {})
}

module "person_overrides_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "person_overrides_mv")
  database = var.database
  name     = "person_overrides_mv"
  to_table = "${var.database}.person_overrides"
  query    = <<-SQL
    SELECT
        team_id,
        old_person_id,
        override_person_id,
        merged_at,
        oldest_event,
        version
    FROM ${var.database}.kafka_person_overrides
  SQL
  override = try(var.overrides["person_overrides_mv"], {})

  depends_on = [
    module.kafka_person_overrides,
    module.person_overrides,
  ]
}
