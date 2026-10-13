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

module "log_entries_main_ro" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "log_entries_main_ro")
  database = var.database
  name     = "log_entries_main_ro"
  override = try(local.deployment.overrides["log_entries_main_ro"], {})
  engine   = "Distributed('${var.database}', '${var.database}', 'sharded_log_entries')"
  columns = [
    { name = "team_id", type = "UInt64" },
    { name = "log_source", type = "LowCardinality(String)" },
    { name = "log_source_id", type = "String" },
    { name = "instance_id", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "level", type = "LowCardinality(String)" },
    { name = "message", type = "String" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ]
}
