variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "deployment" { type = any }

locals {
  deployment = merge({ exclude = [], overrides = {} }, var.deployment)
}

module "person_static_cohort_family" {
  source = "../../lib/table_family"

  name     = "person_static_cohort"
  database = var.database
  layout   = "global"
  columns = [
    { name = "id", type = "UUID" },
    { name = "person_id", type = "UUID" },
    { name = "cohort_id", type = "Int64" },
    { name = "team_id", type = "Int64" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ]
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["_timestamp"]
    order_by    = "(team_id, cohort_id, person_id, id)"
  }
  deployment = local.deployment
}
