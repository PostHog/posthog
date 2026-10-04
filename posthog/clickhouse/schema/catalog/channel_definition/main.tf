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

variable "deployment" { type = any }

locals {
  deployment = merge({ exclude = [], overrides = {} }, var.deployment)
}

terraform {
  required_providers {
    clickhousedbops = {
      source = "PostHog/clickhousedbops"
    }
  }
}

locals {
  storage = contains(local.deployment.components, "storage")
  read    = contains(local.deployment.components, "read")

  # A dictionary source has no PASSWORD clause when the user has no password.
  dictionary_password_clause = var.dictionary_password == "" ? "" : " PASSWORD '${var.dictionary_password}'"
}

# Every node holds its own copy, whose rows are declared below, so recreating the table loses
# nothing. channel_definition_dict reads it, and ClickHouse refuses to drop a table a dictionary
# reads unless the drop skips that check.
module "channel_definition_family" {
  source = "../../lib/table_family"

  name     = "channel_definition"
  database = var.database
  layout   = "global"
  columns = [
    { name = "domain", type = "String" },
    { name = "kind", type = "String" },
    { name = "domain_type", type = "Nullable(String)" },
    { name = "type_if_paid", type = "Nullable(String)" },
    { name = "type_if_organic", type = "Nullable(String)" },
  ]
  # Every node holds its own copy, whose rows are declared below, so recreating the table loses
  # nothing. channel_definition_dict reads it, and ClickHouse refuses to drop a table a dictionary
  # reads unless the drop skips that check.
  storage = {
    replicated = false
    order_by   = "(domain, kind)"
  }
  deployment = merge({
    }, local.deployment, {
    overrides = {
      "channel_definition" = merge({ ignore_drop_dependencies = true, force_destroy = true }, try(local.deployment.overrides["channel_definition"], {}))
    }
  })
}

# Tables that hold data, and the materialized views between them.


# channel_definitions.json is written by `python manage.py create_channel_definitions_file`. Each
# row has a sixth field that the table does not store. A root whose channel_definition is a
# Distributed table over another cluster excludes "channel_definition_contents".
resource "clickhousedbops_table_contents" "channel_definition" {
  count = local.storage && !contains(local.deployment.exclude, "channel_definition") && !contains(local.deployment.exclude, "channel_definition_contents") ? 1 : 0

  database = var.database
  table    = "channel_definition"
  format   = "JSONCompactEachRow"
  data     = join("\n", [for row in jsondecode(file("${path.module}/channel_definitions.json")) : jsonencode(slice(row, 0, 5))])

  depends_on = [module.channel_definition_family]
}

# Distributed tables, views and dictionaries that queries read from.

module "channel_definition_dict" {
  source = "../../lib/dictionary"

  enabled     = local.read && !contains(local.deployment.exclude, "channel_definition_dict")
  database    = var.database
  name        = "channel_definition_dict"
  primary_key = ["domain", "kind"]
  attributes = [
    { name = "domain", type = "String" },
    { name = "kind", type = "String" },
    { name = "domain_type", type = "Nullable(String)" },
    { name = "type_if_paid", type = "Nullable(String)" },
    { name = "type_if_organic", type = "Nullable(String)" },
  ]
  source_clause = "CLICKHOUSE(USER '${var.dictionary_user}'${local.dictionary_password_clause} TABLE 'channel_definition')"
  layout        = "COMPLEX_KEY_HASHED()"
  lifetime      = "MIN 3000 MAX 3600"
  override      = try(local.deployment.overrides["channel_definition_dict"], {})

  depends_on = [
    module.channel_definition_family,
    clickhousedbops_table_contents.channel_definition,
  ]
}
