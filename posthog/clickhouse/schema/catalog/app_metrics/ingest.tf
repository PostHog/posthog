# Kafka tables and the materialized views that consume them.


module "app_metrics2_ws_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(local.deployment.exclude, "app_metrics2_ws_mv")
  database = var.database
  name     = "app_metrics2_ws_mv"
  to_table = "${var.database}.writable_app_metrics2"
  query    = <<-SQL
    SELECT
        team_id,
        timestamp,
        app_source,
        app_source_id,
        instance_id,
        metric_kind,
        metric_name,
        count,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_app_metrics2_ws
  SQL
  override = try(local.deployment.overrides["app_metrics2_ws_mv"], {})

  depends_on = [
    module.kafka_app_metrics2_ws,
    module.sharded_app_metrics2_family,
  ]
}




module "kafka_app_metrics2_ws" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(local.deployment.exclude, "kafka_app_metrics2_ws")
  database = var.database
  name     = "kafka_app_metrics2_ws"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_app_metrics2_ws', kafka_topic_list = 'clickhouse_app_metrics2'"
  columns  = local.kafka_app_metrics2_columns
  override = try(local.deployment.overrides["kafka_app_metrics2_ws"], {})
}

module "kafka_app_metrics" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(local.deployment.exclude, "kafka_app_metrics")
  database = var.database
  name     = "kafka_app_metrics"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'clickhouse_app_metrics'"
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "plugin_config_id", type = "Int64" },
    { name = "category", type = "LowCardinality(String)" },
    { name = "job_id", type = "String" },
    { name = "successes", type = "Int64" },
    { name = "successes_on_retry", type = "Int64" },
    { name = "failures", type = "Int64" },
    { name = "error_uuid", type = "UUID" },
    { name = "error_type", type = "String" },
    { name = "error_details", type = "String", codec = "ZSTD(3)" },
  ]
  override = try(local.deployment.overrides["kafka_app_metrics"], {})
}

module "app_metrics_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(local.deployment.exclude, "app_metrics_mv")
  database = var.database
  name     = "app_metrics_mv"
  to_table = "${var.database}.writable_app_metrics"
  query    = <<-SQL
    SELECT
        team_id,
        timestamp,
        plugin_config_id,
        category,
        job_id,
        successes,
        successes_on_retry,
        failures,
        error_uuid,
        error_type,
        error_details,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_app_metrics
  SQL
  override = try(local.deployment.overrides["app_metrics_mv"], {})

  depends_on = [
    module.kafka_app_metrics,
    module.sharded_app_metrics_family,
  ]
}
