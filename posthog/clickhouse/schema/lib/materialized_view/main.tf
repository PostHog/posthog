terraform {
  required_providers {
    clickhousedbops = {
      source = "PostHog/clickhousedbops"
    }
  }
}

variable "enabled" {
  description = "Create the object on the target nodes."
  type        = bool
  default     = true
}

variable "database" {
  description = "Database the object lives in."
  type        = string
}

variable "name" {
  description = "Object name."
  type        = string
}

variable "node" {
  description = "The server the object lives on: { name, host, port, leader }. Null puts it on the provider's host."
  type        = any
  default     = null
}

variable "override" {
  description = "Changes to the definition for the target nodes. A key that is present wins over the argument of the same name, and `null` clears it."
  type        = any
  default     = {}
}

variable "to_table" {
  description = "Table the view writes to, as `database.table`."
  type        = string
}

variable "query" {
  description = "SELECT the view runs on each inserted block."
  type        = string
}

variable "objects" {
  description = "Names of every object on the node. When set, the view's source and target tables must be among them."
  type        = set(string)
  default     = null
}

locals {
  to_table = try(var.override.to_table, var.to_table)
  query    = try(var.override.query, var.query)
  # Tables of this database the view reads from and writes to. They must be on the same node as the view.
  target  = startswith(replace(local.to_table, "`", ""), "${var.database}.") ? [split(".", replace(local.to_table, "`", ""))[1]] : []
  sources = [for m in regexall("(?i)\\b(?:FROM|JOIN)\\s+`?${var.database}`?\\.`?(\\w+)", local.query) : m[0]]
  absent  = var.objects == null ? [] : [for table in distinct(concat(local.target, local.sources)) : table if !contains(var.objects, table)]
}

resource "clickhousedbops_materialized_view" "this" {
  count = var.enabled ? 1 : 0

  database = var.database
  name     = var.name
  to_table = local.to_table
  query    = local.query

  node = var.node == null ? null : { name = var.node.name, host = var.node.host, port = try(var.node.port, null) }

  lifecycle {
    precondition {
      condition     = length(local.absent) == 0
      error_message = "Materialized view ${var.name} reads from or writes to ${join(", ", local.absent)}, which this node does not have."
    }
  }
}
