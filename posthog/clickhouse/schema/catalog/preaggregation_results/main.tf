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

variable "ttl" {
  description = "Set table TTLs. Tests turn them off, because they insert rows with old timestamps."
  type        = bool
  default     = true
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
  sharded_preaggregation_results_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "time_window_start", type = "DateTime64(6, 'UTC')" },
    { name = "expires_at", type = "DateTime64(6, 'UTC')", default_expression = "now() + toIntervalDay(7)" },
    { name = "breakdown_value", type = "Array(String)" },
    { name = "uniq_exact_state", type = "AggregateFunction(uniqExact, UUID)" },
  ]
}

module "sharded_preaggregation_results_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "preaggregation_results"
  database = var.database
  columns  = local.sharded_preaggregation_results_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toYYYYMM(time_window_start)"
    order_by     = "(team_id, job_id, time_window_start, breakdown_value)"
    ttl          = var.ttl ? "expires_at" : null
  }
  routing = {
    write = false
  }
  sharding_key = "sipHash64(job_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.preaggregation_results"
    cluster     = "posthog"
  }, local.deployment)
}
