# Production objects from before this catalogue, declared from their live definitions. Only Cloud roots
# in posthog-cloud-infra list them.

variable "node" {
  type    = any
  default = null
}

variable "database" {
  type    = string
  default = "posthog"
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

module "sharded_web_bot_definition" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "sharded_web_bot_definition")
  database = var.database
  name     = "sharded_web_bot_definition"
  override = try(local.deployment.overrides["sharded_web_bot_definition"], {})
  engine   = "ReplicatedMergeTree('/clickhouse/tables/{shard}/posthog.sharded_web_bot_definition', '{replica}')"
  order_by = "id"
  settings = "index_granularity = 8192"
  columns = [
    { name = "id", type = "UInt64" },
    { name = "parent_id", type = "UInt64" },
    { name = "regexp", type = "String" },
    { name = "keys", type = "Array(String)" },
    { name = "values", type = "Array(String)" },
  ]
}
