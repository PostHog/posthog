variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "ttl" {
  description = "Set table TTLs. Tests turn them off, because they insert rows with old timestamps."
  type        = bool
  default     = true
}

variable "deployment" { type = any }

locals {
  deployment = merge({ exclude = [], overrides = {} }, var.deployment)
}

module "adhoc_events_deletion_family" {
  source = "../../lib/table_family"

  name     = "adhoc_events_deletion"
  database = var.database
  layout   = "global"
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "uuid", type = "UUID" },
    { name = "data_deletion_request_id", type = "Nullable(UUID)" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
    { name = "deleted_at", type = "DateTime" },
    { name = "is_deleted", type = "UInt8", default_expression = "0" },
  ]
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["deleted_at", "is_deleted"]
    order_by    = "(team_id, uuid)"
    ttl         = var.ttl ? "deleted_at + toIntervalMonth(3) WHERE is_deleted = 1" : null
  }
  deployment = local.deployment
}
