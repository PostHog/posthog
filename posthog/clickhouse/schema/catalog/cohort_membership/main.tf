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

# Column lists that more than one object uses.

locals {
  cohort_membership_columns = [
    { name = "team_id", type = "Int64" },
    { name = "cohort_id", type = "Int64" },
    { name = "person_id", type = "UUID" },
    { name = "status", type = "Enum8('entered' = 1, 'left' = 2)" },
    { name = "last_updated", type = "DateTime64(6)", default_expression = "now64()" },
  ]
}

module "cohort_membership_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "cohort_membership"
  database = var.database
  layout   = "global"
  columns  = local.cohort_membership_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["last_updated"]
    order_by    = "(team_id, cohort_id, person_id)"
  }
  kafka = {
    topic          = "cohort_membership_changed"
    consumer_group = "clickhouse_cohort_membership_changed"
    arguments      = "settings"
    columns = [
      { name = "team_id", type = "Int64" },
      { name = "cohort_id", type = "Int64" },
      { name = "person_id", type = "UUID" },
      { name = "status", type = "Enum8('entered' = 1, 'left' = 2, 'member' = 3, 'not_member' = 4)" },
      { name = "last_updated", type = "DateTime64(6)" },
    ]
    settings = {}
  }
  mv_select  = <<-SQL
team_id,
    cohort_id,
    person_id,
    multiIf(status = 'member', 'entered', status = 'not_member', 'left', status) AS status,
    last_updated
  SQL
  deployment = merge({ kafka_collection = "msk_cluster" }, local.deployment)
}
