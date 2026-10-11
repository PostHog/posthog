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

module "cohortpeople_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "cohortpeople"
  database = var.database
  layout   = "global"
  columns = [
    { name = "person_id", type = "UUID" },
    { name = "cohort_id", type = "Int64" },
    { name = "team_id", type = "Int64" },
    { name = "sign", type = "Int8" },
    { name = "version", type = "UInt64" },
  ]
  storage = {
    engine      = "CollapsingMergeTree"
    engine_args = ["sign"]
    order_by    = "(team_id, cohort_id, person_id, version)"
  }
  deployment = local.deployment
}
