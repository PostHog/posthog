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
  kafka_log_entries_v3_columns = [
    { name = "team_id", type = "UInt64" },
    { name = "log_source", type = "LowCardinality(String)" },
    { name = "log_source_id", type = "String" },
    { name = "instance_id", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "level", type = "LowCardinality(String)" },
    { name = "message", type = "String" },
  ]

  log_entries_data_columns = concat(local.kafka_log_entries_v3_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ])
}

module "log_entries_data_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "log_entries_distributed"
  database = var.database
  columns  = local.log_entries_data_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["_timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    order_by     = "(team_id, log_source, log_source_id, instance_id, timestamp)"
    ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(90)" : null
    settings     = "index_granularity = 1024, ttl_only_drop_parts = 1"
  }
  sharding_key = ""
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.log_entries_data"
    cluster     = "aux"
  }, local.deployment)
  names = { storage = "log_entries_data", write = "writable_log_entries_aux" }
}

module "sharded_log_entries_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "log_entries"
  database = var.database
  columns  = local.log_entries_data_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["_timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    order_by     = "(team_id, log_source, log_source_id, instance_id, timestamp)"
    ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(90)" : null
    settings     = "index_granularity = 1024, ttl_only_drop_parts = 1"
  }
  sharding_key = "rand()"
  routing = {
    read = !var.test
  }
  deployment = merge({ cluster = "posthog" }, local.deployment)
}

module "test_log_entries_family" {
  source = "../../lib/table_family"
  node   = var.node
  # Only the test suite has this table; production has the reader of the same name.
  objects = var.test ? var.objects : []

  name     = "log_entries"
  database = var.database
  layout   = "global"
  columns  = local.log_entries_data_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["_timestamp"]
    partition_by = "toStartOfHour(timestamp)"
    order_by     = "(team_id, log_source, log_source_id, instance_id, timestamp)"
    settings     = "index_granularity = 512"
  }
  # Existing fixtures truncate this entry point directly between Kafka batches.
  deployment = lookup(local.deployment, "keeper_path", null) == null ? {} : { keeper_path = local.deployment.keeper_path }
}

# Kafka tables and the materialized views that consume them.

module "kafka_log_entries_aux" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_log_entries_aux")
  database = var.database
  name     = "kafka_log_entries_aux"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_log_entries_aux', kafka_max_block_size = 100000, kafka_num_consumers = 1, kafka_poll_timeout_ms = 10000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'log_entries'"
  columns  = local.kafka_log_entries_v3_columns
  override = try(local.deployment.overrides["kafka_log_entries_aux"], {})
}

module "kafka_log_entries_v3" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_log_entries_v3")
  database = var.database
  name     = "kafka_log_entries_v3"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_log_entries', kafka_skip_broken_messages = 100, kafka_topic_list = 'log_entries'"
  columns  = local.kafka_log_entries_v3_columns
  override = try(local.deployment.overrides["kafka_log_entries_v3"], {})
}

module "kafka_log_entries_ws" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_log_entries_ws")
  database = var.database
  name     = "kafka_log_entries_ws"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_log_entries_ws', kafka_skip_broken_messages = 100, kafka_topic_list = 'log_entries'"
  columns  = local.kafka_log_entries_v3_columns
  override = try(local.deployment.overrides["kafka_log_entries_ws"], {})
}

module "log_entries_aux_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "log_entries_aux_mv")
  database = var.database
  name     = "log_entries_aux_mv"
  to_table = "${var.database}.writable_log_entries_aux"
  query    = <<-SQL
    SELECT
        team_id,
        log_source,
        log_source_id,
        instance_id,
        timestamp,
        level,
        message,
        _timestamp,
        _offset
    FROM ${var.database}.kafka_log_entries_aux
    WHERE toDate(timestamp) <= today()
  SQL
  override = try(local.deployment.overrides["log_entries_aux_mv"], {})

  depends_on = [
    module.kafka_log_entries_aux,
    module.log_entries_data_family,
  ]
}

module "log_entries_v3_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "log_entries_v3_mv")
  database = var.database
  name     = "log_entries_v3_mv"
  to_table = "${var.database}.writable_log_entries"
  query    = <<-SQL
    SELECT
        team_id,
        log_source,
        log_source_id,
        instance_id,
        timestamp,
        level,
        message,
        _timestamp,
        _offset
    FROM ${var.database}.kafka_log_entries_v3
    WHERE toDate(timestamp) <= today()
  SQL
  override = try(local.deployment.overrides["log_entries_v3_mv"], {})

  depends_on = [
    module.kafka_log_entries_v3,
    module.sharded_log_entries_family,
  ]
}

module "log_entries_ws_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "log_entries_ws_mv")
  database = var.database
  name     = "log_entries_ws_mv"
  to_table = "${var.database}.writable_log_entries"
  query    = <<-SQL
    SELECT
        team_id,
        log_source,
        log_source_id,
        instance_id,
        timestamp,
        level,
        message,
        _timestamp,
        _offset
    FROM ${var.database}.kafka_log_entries_ws
    WHERE toDate(timestamp) <= today()
  SQL
  override = try(local.deployment.overrides["log_entries_ws_mv"], {})

  depends_on = [
    module.kafka_log_entries_ws,
    module.sharded_log_entries_family,
  ]
}
