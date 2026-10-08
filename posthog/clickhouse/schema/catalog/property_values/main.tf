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

# Column lists that more than one object uses.

locals {
  property_values_columns = [
    { name = "team_id", type = "Int64", codec = "DoubleDelta, ZSTD(1)" },
    { name = "property_type", type = "LowCardinality(String)" },
    { name = "property_key", type = "LowCardinality(String)" },
    { name = "property_value", type = "String" },
    { name = "property_count", type = "SimpleAggregateFunction(sum, UInt64)" },
    { name = "last_seen", type = "SimpleAggregateFunction(max, DateTime)", default_expression = "now()" },
  ]
}

module "property_values_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "property_values_distributed"
  database = var.database
  layout   = "global"
  columns  = local.property_values_columns
  storage = {
    engine   = "AggregatingMergeTree"
    order_by = "(team_id, property_type, property_key, property_value)"
    ttl      = var.ttl ? "last_seen + toIntervalDay(30)" : null
    indexes = [
      { name = "idx_property_value_ngrambf", expression = "lower(property_value)", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
    ]
  }
  routing = {
    read         = true
    write        = false
    read_columns = local.property_values_columns
  }
  kafka = {
    topic          = "clickhouse_property_values"
    consumer_group = "clickhouse_property_values"
    arguments      = "settings"
    columns = [
      { name = "team_id", type = "Int64" },
      { name = "property_type", type = "LowCardinality(String)" },
      { name = "property_key", type = "String" },
      { name = "property_value", type = "String" },
      { name = "property_count", type = "UInt64" },
    ]
    settings = { kafka_num_consumers = "1", kafka_thread_per_consumer = "1" }
  }
  mv_select  = <<-SQL
team_id,
    property_type,
    property_key,
    property_value,
    property_count,
    coalesce(_timestamp, now()) AS last_seen
  SQL
  mv_target  = "${var.database}.property_values"
  deployment = merge({ cluster = "aux", kafka_collection = "warpstream_ingestion" }, local.deployment)
  names      = { storage = "property_values", mv = "property_values_mv", kafka = "kafka_property_values" }
}
