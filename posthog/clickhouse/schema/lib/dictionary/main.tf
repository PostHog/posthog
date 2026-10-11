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

variable "attributes" {
  type = list(object({
    name               = string
    type               = string
    default_expression = optional(string)
  }))
}

variable "primary_key" {
  type = list(string)
}

variable "source_clause" {
  description = "Body of the SOURCE clause."
  type        = string
}

variable "layout" {
  type = string
}

variable "lifetime" {
  type = string
}

variable "range" {
  type    = string
  default = null
}

variable "settings" {
  type    = string
  default = null
}

variable "comment" {
  type    = string
  default = null
}

resource "clickhousedbops_dictionary" "this" {
  count = var.enabled ? 1 : 0

  database    = var.database
  name        = var.name
  attributes  = try(var.override.attributes, var.attributes)
  primary_key = try(var.override.primary_key, var.primary_key)
  source      = try(var.override.source_clause, var.source_clause)
  layout      = try(var.override.layout, var.layout)
  lifetime    = try(var.override.lifetime, var.lifetime)
  range       = try(var.override.range, var.range)
  settings    = try(var.override.settings, var.settings)
  comment     = try(var.override.comment, var.comment)

  node = var.node == null ? null : { name = var.node.name, host = var.node.host, port = try(var.node.port, null) }
}
