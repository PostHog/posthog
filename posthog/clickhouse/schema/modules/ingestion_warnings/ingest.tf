# Kafka tables and the materialized views that consume them.

module "ingestion_warnings_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "ingestion_warnings_mv")
  database = var.database
  name     = "ingestion_warnings_mv"
  to_table = "${var.database}.writable_ingestion_warnings"
  query    = <<-SQL
    SELECT
        team_id,
        source,
        type,
        details,
        timestamp,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_ingestion_warnings
  SQL
  override = try(var.overrides["ingestion_warnings_mv"], {})

  depends_on = [
    module.kafka_ingestion_warnings,
    module.writable_ingestion_warnings,
  ]
}

module "ingestion_warnings_v2_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "ingestion_warnings_v2_mv")
  database = var.database
  name     = "ingestion_warnings_v2_mv"
  to_table = "${var.database}.ingestion_warnings_v2"
  query    = <<-SQL
    SELECT
        team_id,
        source,
        type,
        details,
        timestamp,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_ingestion_warnings_v2
  SQL
  override = try(var.overrides["ingestion_warnings_v2_mv"], {})

  depends_on = [
    module.ingestion_warnings_v2,
    module.kafka_ingestion_warnings_v2,
  ]
}

module "kafka_ingestion_warnings" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_ingestion_warnings")
  database = var.database
  name     = "kafka_ingestion_warnings"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'clickhouse_ingestion_warnings'"
  columns  = local.kafka_ingestion_warnings_columns
  override = try(var.overrides["kafka_ingestion_warnings"], {})
}

module "kafka_ingestion_warnings_v2" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_ingestion_warnings_v2")
  database = var.database
  name     = "kafka_ingestion_warnings_v2"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_ingestion_warnings_v2', kafka_topic_list = 'clickhouse_ingestion_warnings'"
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "source", type = "LowCardinality(String)" },
    { name = "type", type = "String" },
    { name = "details", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
  ]
  override = try(var.overrides["kafka_ingestion_warnings_v2"], {})
}
