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

terraform {
  required_providers {
    clickhousedbops = {
      source = "PostHog/clickhousedbops"
    }
  }
}

locals {

  # A dictionary source has no PASSWORD clause when the user has no password.
  dictionary_password_clause = var.dictionary_password == "" ? "" : " PASSWORD '${var.dictionary_password}'"
}

# Column lists that more than one object uses.

locals {
  web_bot_definition_columns = [
    { name = "id", type = "UInt64" },
    { name = "parent_id", type = "UInt64" },
    { name = "regexp", type = "String" },
    { name = "keys", type = "Array(String)" },
    { name = "values", type = "Array(String)" },
  ]
}

# Its rows are declared below, so recreating the table loses nothing. web_bot_definition_dict
# reads it, and ClickHouse refuses to drop a table a dictionary reads unless the drop skips that check.
module "web_bot_definition_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_bot_definition"
  database = var.database
  layout   = "global"
  columns  = local.web_bot_definition_columns
  # Its rows are declared below, so recreating the table loses nothing. web_bot_definition_dict
  # reads it, and ClickHouse refuses to drop a table a dictionary reads unless the drop skips that check.
  storage = {
    replicated = false
    order_by   = "id"
  }
  deployment = merge({
    }, local.deployment, {
    overrides = {
      "web_bot_definition" = merge({ ignore_drop_dependencies = true, force_destroy = true }, try(local.deployment.overrides["web_bot_definition"], {}))
    }
  })
}

# Distributed tables, views and dictionaries that queries read from.

# Every node holds its own copy of the bot definitions, which the dictionary reads locally.
# The table is small and its rows are declared below, so no node reads them from another cluster.

# web_bot_definitions.jsonl is generated from BOT_DEFINITIONS by `python manage.py write_bot_definitions_file`.
resource "clickhousedbops_table_contents" "web_bot_definition" {
  count = contains(var.objects, "web_bot_definition_contents") ? 1 : 0

  database = var.database
  node     = var.node == null ? null : { name = var.node.name, host = var.node.host, port = try(var.node.port, null) }
  table    = "web_bot_definition"
  format   = "JSONCompactEachRow"
  data     = file("${path.module}/web_bot_definitions.jsonl")

  depends_on = [module.web_bot_definition_family]
}

module "web_bot_definition_dict" {
  source = "../../lib/dictionary"
  node   = var.node

  enabled     = contains(var.objects, "web_bot_definition_dict")
  database    = var.database
  name        = "web_bot_definition_dict"
  primary_key = ["regexp"]
  attributes = [
    { name = "regexp", type = "String" },
    { name = "name", type = "String" },
    { name = "category", type = "String" },
    { name = "traffic_type", type = "String" },
    { name = "operator", type = "String" },
  ]
  source_clause = "CLICKHOUSE(USER '${var.dictionary_user}'${local.dictionary_password_clause} DB '${var.database}' TABLE 'web_bot_definition')"
  layout        = "REGEXP_TREE()"
  lifetime      = "MIN 3000 MAX 3600"
  override      = try(local.deployment.overrides["web_bot_definition_dict"], {})

  depends_on = [
    module.web_bot_definition_family,
    clickhousedbops_table_contents.web_bot_definition,
  ]
}
