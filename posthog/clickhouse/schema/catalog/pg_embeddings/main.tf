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

module "pg_embeddings_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "pg_embeddings"
  database = var.database
  layout   = "global"
  columns = [
    { name = "domain", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "id", type = "String" },
    { name = "vector", type = "Array(Float32)" },
    { name = "text", type = "String" },
    { name = "properties", type = "String", codec = "ZSTD(3)" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')", default_expression = "now('UTC')" },
    { name = "is_deleted", type = "UInt8" },
  ]
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["timestamp", "is_deleted"]
    order_by    = "(team_id, domain, id)"
    settings    = "index_granularity = 512"
  }
  deployment = local.deployment
}
