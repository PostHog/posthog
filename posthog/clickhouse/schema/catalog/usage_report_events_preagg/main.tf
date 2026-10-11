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
  sharded_usage_report_events_preagg_columns = [
    { name = "date", type = "Date" },
    { name = "team_id", type = "Int64" },
    { name = "person_mode", type = "LowCardinality(String)" },
    { name = "lib", type = "LowCardinality(String)" },
    { name = "event", type = "String" },
    { name = "distinct_events_unique", type = "AggregateFunction(uniqExact, Tuple(UInt64, UInt64, UInt64))" },
    { name = "event_count", type = "AggregateFunction(sum, UInt64)" },
  ]
}

module "sharded_usage_report_events_preagg_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "usage_report_events_preagg"
  database = var.database
  columns  = local.sharded_usage_report_events_preagg_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "date"
    order_by     = "(date, team_id, person_mode, lib, event)"
    ttl          = var.ttl ? "date + toIntervalDay(14)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  sharding_key = "sipHash64(date)"
  deployment   = merge({ cluster = "aux" }, local.deployment)
}

# Kafka tables and the materialized views that consume them.

module "kafka_usage_report_events_preagg" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_usage_report_events_preagg")
  database = var.database
  name     = "kafka_usage_report_events_preagg"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_usage_report_events_preagg', kafka_num_consumers = 1, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_events_json'"
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "String" },
    { name = "properties", type = "String", codec = "ZSTD(3)" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "person_mode", type = "Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)" },
  ]
  override = try(local.deployment.overrides["kafka_usage_report_events_preagg"], {})
}

module "usage_report_events_preagg_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "usage_report_events_preagg_mv")
  database = var.database
  name     = "usage_report_events_preagg_mv"
  to_table = "${var.database}.writable_usage_report_events_preagg"
  query    = <<-SQL
    SELECT
        toDate(timestamp) AS date,
        team_id,
        person_mode,
        JSONExtractString(properties, '$lib') AS lib,
        event,
        uniqExactState((cityHash64(distinct_id), cityHash64(toString(uuid)), cityHash64(event))) AS distinct_events_unique,
        sumState(toUInt64(1)) AS event_count
    FROM ${var.database}.kafka_usage_report_events_preagg
    GROUP BY
        date,
        team_id,
        person_mode,
        lib,
        event
  SQL
  override = try(local.deployment.overrides["usage_report_events_preagg_mv"], {})

  depends_on = [
    module.kafka_usage_report_events_preagg,
    module.sharded_usage_report_events_preagg_family,
  ]
}
