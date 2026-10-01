# Kafka tables and the materialized views that consume them.

module "kafka_person_distinct_id" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_person_distinct_id")
  database = var.database
  name     = "kafka_person_distinct_id"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'clickhouse_person_unique_id'"
  columns = [
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "UUID" },
    { name = "team_id", type = "Int64" },
    { name = "_sign", type = "Nullable(Int8)" },
    { name = "is_deleted", type = "Nullable(Int8)" },
  ]
  override = try(var.overrides["kafka_person_distinct_id"], {})
}

module "kafka_person_distinct_id2" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_person_distinct_id2")
  database = var.database
  name     = "kafka_person_distinct_id2"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'clickhouse_person_distinct_id'"
  columns  = local.kafka_person_distinct_id2_columns
  override = try(var.overrides["kafka_person_distinct_id2"], {})
}

module "person_distinct_id2_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "person_distinct_id2_mv")
  database = var.database
  name     = "person_distinct_id2_mv"
  to_table = "${var.database}.writable_person_distinct_id2"
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
    FROM ${var.database}.kafka_person_distinct_id2
  SQL
  override = try(var.overrides["person_distinct_id2_mv"], {})

  depends_on = [
    module.kafka_person_distinct_id2,
    module.writable_person_distinct_id2,
  ]
}

module "person_distinct_id_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "person_distinct_id_mv")
  database = var.database
  name     = "person_distinct_id_mv"
  to_table = "${var.database}.person_distinct_id"
  query    = <<-SQL
    SELECT
        distinct_id,
        person_id,
        team_id,
        coalesce(_sign, if(is_deleted = 0, 1, -1)) AS _sign,
        _timestamp,
        _offset
    FROM ${var.database}.kafka_person_distinct_id
  SQL
  override = try(var.overrides["person_distinct_id_mv"], {})

  depends_on = [
    module.kafka_person_distinct_id,
    module.person_distinct_id,
  ]
}
