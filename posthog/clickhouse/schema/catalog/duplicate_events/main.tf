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
  duplicate_events_columns = [
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "event", type = "String" },
    { name = "source_uuid", type = "UUID" },
    { name = "duplicate_uuid", type = "UUID" },
    { name = "similarity_score", type = "Float64" },
    { name = "dedup_type", type = "LowCardinality(String)" },
    { name = "is_confirmed", type = "UInt8" },
    { name = "reason", type = "Nullable(String)" },
    { name = "version", type = "String" },
    { name = "different_property_count", type = "UInt32" },
    { name = "properties_similarity", type = "Float64" },
    { name = "source_message", type = "String" },
    { name = "duplicate_message", type = "String" },
    { name = "distinct_fields", type = "Array(Tuple(field_name String, original_value String, new_value String))" },
    { name = "inserted_at", type = "DateTime64(3, 'UTC')" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
}

module "duplicate_events_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "duplicate_events"
  database = var.database
  layout   = "global"
  columns  = local.duplicate_events_columns
  storage = {
    partition_by = "toYYYYMMDD(inserted_at)"
    order_by     = "(team_id, distinct_id, event, inserted_at)"
    ttl          = var.ttl ? "inserted_at + toIntervalDay(7)" : null
    settings     = "index_granularity = 512"
    indexes = [
      { name = "kafka_timestamp_minmax_duplicate_events", expression = "_timestamp", type = "minmax", granularity = 3 },
    ]
  }
  kafka = {
    topic     = "clickhouse_ingestion_events_duplicates"
    arguments = "settings"
    columns = [
      { name = "team_id", type = "Int64" },
      { name = "distinct_id", type = "String" },
      { name = "event", type = "String" },
      { name = "source_uuid", type = "UUID" },
      { name = "duplicate_uuid", type = "UUID" },
      { name = "similarity_score", type = "Float64" },
      { name = "dedup_type", type = "LowCardinality(String)" },
      { name = "is_confirmed", type = "UInt8" },
      { name = "reason", type = "Nullable(String)" },
      { name = "version", type = "String" },
      { name = "different_property_count", type = "UInt32" },
      { name = "properties_similarity", type = "Float64" },
      { name = "source_message", type = "String" },
      { name = "duplicate_message", type = "String" },
      { name = "distinct_fields", type = "String" },
      { name = "inserted_at", type = "DateTime64(3, 'UTC')" },
    ]
    settings = {}
  }
  mv_select  = <<-SQL
team_id,
    distinct_id,
    event,
    source_uuid,
    duplicate_uuid,
    similarity_score,
    dedup_type,
    is_confirmed,
    reason,
    version,
    different_property_count,
    properties_similarity,
    source_message,
    duplicate_message,
    JSONExtract(distinct_fields, 'Array(Tuple(field_name String, original_value String, new_value String))') AS distinct_fields,
    inserted_at,
    _timestamp,
    _offset,
    _partition
  SQL
  deployment = merge({ kafka_collection = "msk_cluster" }, local.deployment)
}
