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

# Distributed tables, views and dictionaries that queries read from.

module "distributed_system_processes" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "distributed_system_processes")
  database = var.database
  name     = "distributed_system_processes"
  engine   = "Distributed('posthog', 'system', 'processes')"
  settings = "skip_unavailable_shards = 1"
  columns = [
    { name = "is_initial_query", type = "UInt8" },
    { name = "user", type = "String" },
    { name = "query_id", type = "String" },
    { name = "address", type = "IPv6" },
    { name = "port", type = "UInt16" },
    { name = "initial_user", type = "String" },
    { name = "initial_query_id", type = "String" },
    { name = "initial_address", type = "IPv6" },
    { name = "initial_port", type = "UInt16" },
    { name = "interface", type = "UInt8" },
    { name = "os_user", type = "String" },
    { name = "client_hostname", type = "String" },
    { name = "client_name", type = "String" },
    { name = "client_agent", type = "LowCardinality(String)" },
    { name = "client_revision", type = "UInt64" },
    { name = "client_version_major", type = "UInt64" },
    { name = "client_version_minor", type = "UInt64" },
    { name = "client_version_patch", type = "UInt64" },
    { name = "http_method", type = "UInt8" },
    { name = "http_user_agent", type = "String" },
    { name = "http_referer", type = "String" },
    { name = "forwarded_for", type = "String" },
    { name = "quota_key", type = "String" },
    { name = "distributed_depth", type = "UInt64" },
    { name = "elapsed", type = "Float64" },
    { name = "is_cancelled", type = "UInt8" },
    { name = "is_all_data_sent", type = "UInt8" },
    { name = "read_rows", type = "UInt64" },
    { name = "read_bytes", type = "UInt64" },
    { name = "total_rows_approx", type = "UInt64" },
    { name = "written_rows", type = "UInt64" },
    { name = "written_bytes", type = "UInt64" },
    { name = "memory_usage", type = "Int64" },
    { name = "peak_memory_usage", type = "Int64" },
    { name = "query", type = "String" },
    { name = "normalized_query_hash", type = "UInt64" },
    { name = "query_kind", type = "String" },
    { name = "thread_ids", type = "Array(UInt64)" },
    { name = "peak_threads_usage", type = "UInt64" },
    { name = "ProfileEvents", type = "Map(LowCardinality(String), UInt64)" },
    { name = "Settings", type = "Map(LowCardinality(String), LowCardinality(String))" },
    { name = "current_database", type = "String" },
    { name = "is_internal", type = "UInt8" },
    { name = "ProfileEvents.Names", type = "Array(String)", alias_expression = "mapKeys(ProfileEvents)" },
    { name = "ProfileEvents.Values", type = "Array(UInt64)", alias_expression = "mapValues(ProfileEvents)" },
    { name = "Settings.Names", type = "Array(String)", alias_expression = "mapKeys(Settings)" },
    { name = "Settings.Values", type = "Array(String)", alias_expression = "mapValues(Settings)" },
  ]
  override = try(local.deployment.overrides["distributed_system_processes"], {})
}
