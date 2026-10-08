variable "node" {
  description = "The server these objects live on: { name, host, port, leader }. Null puts them on the provider's host."
  type        = any
  default     = null
}

variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "ttl" {
  description = "Set table TTLs. Tests turn them off, because they insert rows with old timestamps."
  type        = bool
  default     = true
}

variable "objects" {
  description = "Names of the objects to create."
  type        = set(string)
}

variable "test" {
  description = "Use the definitions the test suite expects."
  type        = bool
  default     = false
}

variable "deployment" { type = any }

locals {
  deployment = merge({ overrides = {} }, var.deployment)
}

locals {
}

# Column lists that more than one object uses.

locals {
  kafka_app_metrics2_columns = [
    { name = "team_id", type = "Int64" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "app_source", type = "LowCardinality(String)" },
    { name = "app_source_id", type = "String" },
    { name = "instance_id", type = "String" },
    { name = "metric_kind", type = "String" },
    { name = "metric_name", type = "String" },
    { name = "count", type = "Int64" },
  ]

  sharded_app_metrics2_columns = [
    { name = "team_id", type = "Int64" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "app_source", type = "LowCardinality(String)" },
    { name = "app_source_id", type = "String" },
    { name = "instance_id", type = "String" },
    { name = "metric_kind", type = "LowCardinality(String)" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]

  sharded_app_metrics_columns = [
    { name = "team_id", type = "Int64" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "plugin_config_id", type = "Int64" },
    { name = "category", type = "LowCardinality(String)" },
    { name = "job_id", type = "String" },
    { name = "successes", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "successes_on_retry", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "failures", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "error_uuid", type = "UUID" },
    { name = "error_type", type = "String" },
    { name = "error_details", type = "String", codec = "ZSTD(3)" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
}

module "sharded_app_metrics_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

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
  deployment   = merge({ cluster = "posthog", kafka_collection = "msk_cluster" }, local.deployment)
}

module "sharded_app_metrics2_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

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
  mv_select  = <<-SQL
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
  deployment = merge({ cluster = "posthog", kafka_collection = "msk_cluster" }, local.deployment)
}

# Kafka tables and the materialized views that consume them.


module "app_metrics2_ws_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "app_metrics2_ws_mv")
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
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_app_metrics2_ws")
  database = var.database
  name     = "kafka_app_metrics2_ws"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_app_metrics2_ws', kafka_topic_list = 'clickhouse_app_metrics2'"
  columns  = local.kafka_app_metrics2_columns
  override = try(local.deployment.overrides["kafka_app_metrics2_ws"], {})
}

module "kafka_app_metrics" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_app_metrics")
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
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "app_metrics_mv")
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
