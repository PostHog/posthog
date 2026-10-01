terraform {
  required_providers {
    clickhousedbops = { source = "PostHog/clickhousedbops" }
  }
}

variable "database" { type = string }
variable "host" { type = string }
variable "username" { type = string }
variable "password" {
  type      = string
  sensitive = true
}
variable "bad_indexes" {
  type    = bool
  default = false
}

provider "clickhousedbops" {
  host     = var.host
  port     = 9000
  protocol = "native"
  auth_config = {
    strategy = "password"
    username = var.username
    password = var.password == "" ? null : var.password
  }
}

resource "clickhousedbops_database" "test" { name = var.database }

locals {
  input_columns = [
    { name = "team_id", type = "UInt64" },
    { name = "timestamp", type = "DateTime" },
    { name = "value", type = "UInt64" },
  ]
  stored_columns = concat([
    { name = "team_id", type = "UInt64", codec = "Delta(8), ZSTD(1)" },
    { name = "timestamp", type = "DateTime" },
    { name = "value", type = "UInt64" },
  ], [{ name = "doubled", type = "UInt64", materialized_expression = "value * 2" }])
  storage = {
    order_by    = "(team_id, timestamp)"
    indexes     = [{ name = "team_id_idx", expression = "team_id", type = "minmax", granularity = 1 }]
    projections = [{ name = "by_team", query = "SELECT team_id, sum(value) GROUP BY team_id" }]
    constraints = [{ name = "positive_team", check = "team_id > 0" }]
  }
}

module "sharded" {
  source = "../../"

  name     = "family"
  database = clickhousedbops_database.test.name
  columns  = local.stored_columns
  storage  = local.storage
  kafka = {
    topic   = "${var.database}_input"
    columns = local.input_columns
  }
  mv_select = "team_id, timestamp, value"
  deployment = {
    components = ["storage", "read", "write", "ingest"]
    cluster    = "aux"
    overrides = merge({ sharded_family = { force_destroy = true } }, var.bad_indexes ? {
      family = { add_indexes = [{ name = "invalid", expression = "team_id", type = "minmax", granularity = 1 }] }
    } : {})
  }
}

module "global" {
  source = "../../"

  name     = "reference"
  database = clickhousedbops_database.test.name
  layout   = "global"
  columns  = local.stored_columns
  storage  = local.storage
  kafka = {
    topic   = "${var.database}_reference_input"
    columns = local.input_columns
  }
  mv_select = "team_id, timestamp, value"
  deployment = {
    components = ["storage", "write", "ingest"]
    cluster    = "posthog"
    overrides  = { reference = { force_destroy = true } }
  }
}

module "query" {
  source = "../../"

  name     = "family"
  database = clickhousedbops_database.test.name
  columns  = local.stored_columns
  storage  = local.storage
  names    = { read = "routed_read", write = "routed_write" }
  deployment = {
    components = ["read", "write"]
    cluster    = "aux"
  }
}
