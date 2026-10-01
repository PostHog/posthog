module "sharded_app_metrics_family" {
  source = "../../lib/table_family"

  name     = "app_metrics"
  database = var.database
  columns  = local.sharded_app_metrics_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toYYYYMM(timestamp)"
    order_by     = "(team_id, plugin_config_id, job_id, category, toStartOfHour(timestamp), error_type, error_uuid)"
  }
  routing = {
    read_columns  = local.sharded_app_metrics_columns
    write_columns = local.sharded_app_metrics_columns
  }
  sharding_key = "rand()"
  deployment = merge({
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_app_metrics", "app_metrics", "writable_app_metrics"], name) }
  })
}

module "sharded_app_metrics2_family" {
  source = "../../lib/table_family"

  name     = "app_metrics2"
  database = var.database
  columns  = local.sharded_app_metrics2_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toYYYYMM(timestamp)"
    order_by     = "(team_id, app_source, app_source_id, instance_id, toStartOfHour(timestamp), metric_kind, metric_name)"
    ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(90)" : null
  }
  sharding_key = "rand()"
  kafka = {
    topic          = "clickhouse_app_metrics2"
    consumer_group = "group1"
    arguments      = "settings"
    columns        = local.kafka_app_metrics2_columns
    settings       = {}
  }
  mv_select = <<-SQL
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
  SQL
  deployment = merge({
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_app_metrics2", "app_metrics2", "writable_app_metrics2", "app_metrics2_mv", "kafka_app_metrics2"], name) }
  })
}
