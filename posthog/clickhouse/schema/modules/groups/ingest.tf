# Kafka tables and the materialized views that consume them.

module "groups_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "groups_mv")
  database = var.database
  name     = "groups_mv"
  to_table = "${var.database}.writable_groups"
  query    = <<-SQL
    SELECT
        group_type_index,
        group_key,
        created_at,
        team_id,
        group_properties,
        _timestamp,
        _offset
    FROM ${var.database}.kafka_groups
  SQL
  override = try(var.overrides["groups_mv"], {})

  depends_on = [
    module.kafka_groups,
    module.writable_groups,
  ]
}

module "kafka_groups" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_groups")
  database = var.database
  name     = "kafka_groups"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'clickhouse_groups'"
  columns  = local.kafka_groups_columns
  override = try(var.overrides["kafka_groups"], {})
}
