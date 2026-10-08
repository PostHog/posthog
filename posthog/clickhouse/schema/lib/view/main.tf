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

variable "query" {
  description = "SELECT the view runs."
  type        = string
}

resource "clickhousedbops_view" "this" {
  count = var.enabled ? 1 : 0

  database = var.database
  name     = var.name
  query    = try(var.override.query, var.query)

  node = var.node == null ? null : { name = var.node.name, host = var.node.host, port = try(var.node.port, null) }
}
