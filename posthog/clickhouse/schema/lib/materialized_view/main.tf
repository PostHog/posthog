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

resource "clickhousedbops_materialized_view" "this" {
  count = var.enabled ? 1 : 0

  database = var.database
  name     = var.name
  to_table = try(var.override.to_table, var.to_table)
  query    = try(var.override.query, var.query)
}
