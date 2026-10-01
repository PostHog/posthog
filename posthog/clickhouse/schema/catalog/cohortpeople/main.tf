variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "deployment" { type = any }

locals {
  deployment = merge({ exclude = [], overrides = {} }, var.deployment)
}

module "cohortpeople_family" {
  source = "../../lib/table_family"

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
