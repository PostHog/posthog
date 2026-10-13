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

module "asyncdeletion" {
  source = "../../lib/table"
  node   = var.node

  enabled      = contains(var.objects, "asyncdeletion")
  database     = var.database
  name         = "asyncdeletion"
  override     = try(local.deployment.overrides["asyncdeletion"], {})
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/asyncdeletion', '{replica}-{shard}')"
  partition_by = "toYYYYMM(created_at)"
  order_by     = "(deletion_type, delete_verified_at)"
  settings     = "default_compression_codec = 'lz4', index_granularity = 8192"
  columns = [
    { name = "id", type = "UInt64" },
    { name = "deletion_type", type = "UInt8" },
    { name = "key", type = "String" },
    { name = "group_type_index", type = "UInt64" },
    { name = "created_at", type = "DateTime" },
    { name = "delete_verified_at", type = "DateTime" },
    { name = "created_by_id", type = "UInt64" },
    { name = "team_id", type = "UInt64" },
  ]
}

module "async_deletion_run" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "async_deletion_run")
  database = var.database
  name     = "async_deletion_run"
  override = try(local.deployment.overrides["async_deletion_run"], {})
  engine   = "Join(ANY, LEFT, team_id, deletion_type, key)"
  columns = [
    { name = "id", type = "UInt64" },
    { name = "deletion_type", type = "UInt8" },
    { name = "key", type = "String" },
    { name = "group_type_index", type = "String" },
    { name = "team_id", type = "Int64" },
  ]
}
