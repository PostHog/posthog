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
  kafka_tophog_columns = [
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "metric", type = "LowCardinality(String)" },
    { name = "type", type = "LowCardinality(String)" },
    { name = "key", type = "Map(LowCardinality(String), String)" },
    { name = "value", type = "Float64" },
    { name = "count", type = "UInt64" },
    { name = "pipeline", type = "LowCardinality(String)" },
    { name = "lane", type = "LowCardinality(String)" },
    { name = "labels", type = "Map(LowCardinality(String), String)" },
  ]

  sharded_tophog_columns = [
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "metric", type = "LowCardinality(String)" },
    { name = "type", type = "LowCardinality(String)", default_expression = "'sum'" },
    { name = "key", type = "Map(LowCardinality(String), String)" },
    { name = "value", type = "Float64" },
    { name = "count", type = "UInt64", default_expression = "0" },
    { name = "pipeline", type = "LowCardinality(String)" },
    { name = "lane", type = "LowCardinality(String)" },
    { name = "labels", type = "Map(LowCardinality(String), String)" },
  ]
}

module "sharded_tophog_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "tophog"
  database = var.database
  columns  = local.sharded_tophog_columns
  storage = {
    partition_by = "toYYYYMMDD(timestamp)"
    order_by     = "(pipeline, lane, metric, timestamp, key)"
    ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(30)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  sharding_key = "cityHash64(toString(key))"
  kafka = {
    topic     = "clickhouse_tophog"
    arguments = "settings"
    columns   = local.kafka_tophog_columns
    settings  = { date_time_input_format = "'best_effort'", kafka_skip_broken_messages = "100" }
  }
  mv_select = <<-SQL
timestamp,
    metric,
    type,
    key,
    value,
    count,
    pipeline,
    lane,
    labels
  SQL
  deployment = merge({
    keeper_path      = "/clickhouse/tables/{shard}/${var.database}.tophog"
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
  }, local.deployment)
}

# Kafka tables and the materialized views that consume them.


module "kafka_tophog_ws" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_tophog_ws")
  database = var.database
  name     = "kafka_tophog_ws"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "date_time_input_format = 'best_effort', kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_tophog_ws', kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_tophog'"
  columns  = local.kafka_tophog_columns
  override = try(local.deployment.overrides["kafka_tophog_ws"], {})
}


module "tophog_ws_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "tophog_ws_mv")
  database = var.database
  name     = "tophog_ws_mv"
  to_table = "${var.database}.writable_tophog"
  query    = <<-SQL
    SELECT
        timestamp,
        metric,
        type,
        key,
        value,
        count,
        pipeline,
        lane,
        labels
    FROM ${var.database}.kafka_tophog_ws
  SQL
  override = try(local.deployment.overrides["tophog_ws_mv"], {})

  depends_on = [
    module.kafka_tophog_ws,
    module.sharded_tophog_family,
  ]
}
