
module "kafka_ingestion_warnings" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(local.deployment.exclude, "kafka_ingestion_warnings")
  database = var.database
  name     = "kafka_ingestion_warnings"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'clickhouse_ingestion_warnings'"
  columns  = local.kafka_ingestion_warnings_columns
  override = try(local.deployment.overrides["kafka_ingestion_warnings"], {})
}

module "ingestion_warnings_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(local.deployment.exclude, "ingestion_warnings_mv")
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
  override = try(local.deployment.overrides["ingestion_warnings_mv"], {})

  depends_on = [
    module.kafka_ingestion_warnings,
    module.sharded_ingestion_warnings_family,
  ]
}
