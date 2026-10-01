# Kafka tables and the materialized views that consume them.

module "kafka_person_distinct_id_overrides" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(local.deployment.exclude, "kafka_person_distinct_id_overrides")
  database = var.database
  name     = "kafka_person_distinct_id_overrides"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse-person-distinct-id-overrides', kafka_topic_list = 'clickhouse_person_distinct_id'"
  columns  = local.kafka_person_distinct_id_overrides_columns
  override = try(local.deployment.overrides["kafka_person_distinct_id_overrides"], {})
}

module "person_distinct_id_overrides_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(local.deployment.exclude, "person_distinct_id_overrides_mv")
  database = var.database
  name     = "person_distinct_id_overrides_mv"
  to_table = "${var.database}.writable_person_distinct_id_overrides"
  query    = <<-SQL
    SELECT
        team_id,
        distinct_id,
        person_id,
        is_deleted,
        version,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_person_distinct_id_overrides
    WHERE version > 0
  SQL
  override = try(local.deployment.overrides["person_distinct_id_overrides_mv"], {})

  depends_on = [
    module.kafka_person_distinct_id_overrides,
    module.person_distinct_id_overrides_family,
  ]
}
