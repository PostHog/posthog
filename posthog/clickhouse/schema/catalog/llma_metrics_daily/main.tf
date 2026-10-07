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

module "llma_metrics_daily_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "llma_metrics_daily"
  database = var.database
  layout   = "global"
  columns = [
    { name = "date", type = "Date" },
    { name = "team_id", type = "UInt64" },
    { name = "metric_name", type = "String" },
    { name = "metric_value", type = "Float64" },
  ]
  storage = {
    partition_by = "toYYYYMM(date)"
    order_by     = "(team_id, date, metric_name)"
  }
  deployment = local.deployment
}
