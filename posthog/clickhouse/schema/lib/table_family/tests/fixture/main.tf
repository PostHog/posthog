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
    topic   = "${var.database}_input,${var.database}_extra"
    columns = local.input_columns
  }
  mv_select = "team_id, timestamp, value"
  objects   = ["sharded_family", "family", "writable_family", "kafka_family", "family_mv"]
  deployment = {
    cluster            = "aux"
    kafka_topic_prefix = "isolated_"
    kafka_topic_suffix = "_test"
    overrides = merge({ sharded_family = { force_destroy = true }, sibling_storage = { indexes = [] } }, var.bad_indexes ? {
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
    topic     = "${var.database}_reference_input"
    columns   = local.input_columns
    arguments = "settings"
  }
  mv_select = "team_id, timestamp, value"
  mv_target = "${var.database}.reference"
  routing   = { read = true }
  names     = { read = "reference_read" }
  objects   = ["reference", "reference_read", "writable_reference", "kafka_reference", "reference_mv"]
  deployment = {
    cluster            = "posthog"
    kafka_topic_suffix = "_test"
    overrides          = { reference = { force_destroy = true } }
  }
}

module "plain" {
  source = "../../"

  name     = "plain_reference"
  database = clickhousedbops_database.test.name
  layout   = "global"
  columns  = local.input_columns
  storage  = { replicated = false, order_by = "team_id" }
  objects  = ["plain_reference"]
}

module "query" {
  source = "../../"

  name     = "family"
  database = clickhousedbops_database.test.name
  columns  = local.stored_columns
  storage  = local.storage
  names    = { read = "routed_read", write = "routed_write" }
  objects  = ["routed_read", "routed_write"]
  deployment = {
    cluster = "aux"
  }
}
