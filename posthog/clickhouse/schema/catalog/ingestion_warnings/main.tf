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
  kafka_ingestion_warnings_columns = [
    { name = "team_id", type = "Int64" },
    { name = "source", type = "LowCardinality(String)" },
    { name = "type", type = "String" },
    { name = "details", type = "String", codec = "ZSTD(3)" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
  ]

  sharded_ingestion_warnings_columns = concat(local.kafka_ingestion_warnings_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])

  ingestion_warnings_v2_columns = [
    { name = "team_id", type = "Int64" },
    { name = "source", type = "LowCardinality(String)" },
    { name = "type", type = "LowCardinality(String)" },
    { name = "details", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "category", type = "LowCardinality(String)", default_expression = "coalesce(nullIf(JSONExtractString(details, 'category'), ''), 'unknown')" },
    { name = "severity", type = "LowCardinality(String)", default_expression = "coalesce(nullIf(JSONExtractString(details, 'severity'), ''), 'warning')" },
    { name = "pipeline_step", type = "LowCardinality(String)", default_expression = "coalesce(nullIf(JSONExtractString(details, 'pipelineStep'), ''), 'unknown')" },
    { name = "event_uuid", type = "Nullable(UUID)", default_expression = "toUUIDOrNull(JSONExtractString(details, 'eventUuid'))" },
    { name = "distinct_id", type = "Nullable(String)", default_expression = "nullIf(JSONExtractString(details, 'distinctId'), '')" },
    { name = "group_key", type = "Nullable(String)", default_expression = "nullIf(JSONExtractString(details, 'groupKey'), '')" },
    { name = "person_id", type = "Nullable(UUID)", default_expression = "toUUIDOrNull(JSONExtractString(details, 'personId'))" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
}

module "ingestion_warnings_v2_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "ingestion_warnings_v2_distributed"
  database = var.database
  layout   = "global"
  columns  = local.ingestion_warnings_v2_columns
  storage = {
    partition_by = "toYYYYMM(timestamp)"
    order_by     = "(team_id, type, timestamp)"
    ttl          = var.ttl ? "toDateTime(timestamp) + toIntervalDay(90)" : null
  }
  routing = {
    read  = true
    write = false
  }
  kafka = {
    topic          = "clickhouse_ingestion_warnings"
    consumer_group = "clickhouse_ingestion_warnings_v2"
    arguments      = "settings"
    columns = [
      { name = "team_id", type = "Int64" },
      { name = "source", type = "LowCardinality(String)" },
      { name = "type", type = "String" },
      { name = "details", type = "String" },
      { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    ]
    settings = {}
  }
  mv_select  = <<-SQL
team_id,
    source,
    type,
    details,
    timestamp,
    _timestamp,
    _offset,
    _partition
  SQL
  mv_target  = "${var.database}.ingestion_warnings_v2"
  deployment = merge({ cluster = "aux", kafka_collection = "warpstream_ingestion" }, local.deployment)
  names      = { storage = "ingestion_warnings_v2", mv = "ingestion_warnings_v2_mv", kafka = "kafka_ingestion_warnings_v2" }
}

module "sharded_ingestion_warnings_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "ingestion_warnings"
  database = var.database
  columns  = local.sharded_ingestion_warnings_columns
  storage = {
    partition_by = "toYYYYMMDD(timestamp)"
    order_by     = "(team_id, toHour(timestamp), type, source, timestamp)"
  }
  routing = {
    read_columns  = local.sharded_ingestion_warnings_columns
    write_columns = local.sharded_ingestion_warnings_columns
  }
  sharding_key = "rand()"
  deployment   = merge({ cluster = "posthog", kafka_collection = "msk_cluster" }, local.deployment)
}

module "kafka_ingestion_warnings" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_ingestion_warnings")
  database = var.database
  name     = "kafka_ingestion_warnings"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'clickhouse_ingestion_warnings'"
  columns  = local.kafka_ingestion_warnings_columns
  override = try(local.deployment.overrides["kafka_ingestion_warnings"], {})
}

module "ingestion_warnings_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "ingestion_warnings_mv")
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
