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

module "person_collapsing" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "person_collapsing")
  database = var.database
  name     = "person_collapsing"
  override = try(local.deployment.overrides["person_collapsing"], {})
  engine   = "ReplicatedCollapsingMergeTree('/clickhouse/prod/tables/noshard/posthog.person_collapsing', '{replica}-{shard}', _sign)"
  order_by = "(team_id, id)"
  settings = "default_compression_codec = 'lz4', index_granularity = 8192"
  columns = [
    { name = "id", type = "UUID" },
    { name = "created_at", type = "DateTime64(3)" },
    { name = "team_id", type = "Int64" },
    { name = "properties", type = "String" },
    { name = "is_identified", type = "Int8" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_sign", type = "Int8" },
  ]
}
