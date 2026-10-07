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

variable "dictionary_user" {
  description = "User the dictionaries connect to their source as."
  type        = string
  default     = "default"
}

variable "dictionary_password" {
  description = "Password of `dictionary_user`."
  type        = string
  default     = ""
  sensitive   = true
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
  test = var.test

  # A dictionary source has no PASSWORD clause when the user has no password.
  dictionary_password_clause = var.dictionary_password == "" ? "" : " PASSWORD '${var.dictionary_password}'"
}

module "dmat_slot_assignments_family" {
  source = "../../lib/table_family"
  node   = var.node
  # Only the test suite has this table.
  objects = var.test ? var.objects : []

  name     = "dmat_slot_assignments"
  database = var.database
  layout   = "global"
  columns = [
    { name = "team_id", type = "UInt64" },
    { name = "column_index", type = "UInt8" },
    { name = "property_name", type = "String" },
    { name = "version", type = "UInt32", default_expression = "toUnixTimestamp(now())" },
  ]
  storage = {
    engine      = "ReplacingMergeTree"
    replicated  = false
    engine_args = ["version"]
    order_by    = "(team_id, column_index)"
  }
  deployment = merge({
    }, local.deployment, {
    overrides = { for name, override in local.deployment.overrides : name => override if contains(["dmat_slot_assignments"], name) }
  })
}

# Objects only the test suite uses, such as materialized views that stand in for the kafka pipeline.


module "dmat_slot_assignments_dict" {
  source = "../../lib/dictionary"
  node   = var.node

  enabled     = contains(var.objects, "dmat_slot_assignments_dict")
  database    = var.database
  name        = "dmat_slot_assignments_dict"
  primary_key = ["team_id", "column_index"]
  attributes = [
    { name = "team_id", type = "UInt64" },
    { name = "column_index", type = "UInt8" },
    { name = "property_name", type = "String" },
  ]
  source_clause = "CLICKHOUSE(QUERY 'SELECT     team_id,     column_index,     property_name FROM     `${var.database}`.`dmat_slot_assignments` FINAL' USER '${var.dictionary_user}'${local.dictionary_password_clause})"
  layout        = "COMPLEX_KEY_HASHED()"
  lifetime      = "MIN 600 MAX 1200"
  override      = try(local.deployment.overrides["dmat_slot_assignments_dict"], {})

  depends_on = [
    module.dmat_slot_assignments_family,
  ]
}
