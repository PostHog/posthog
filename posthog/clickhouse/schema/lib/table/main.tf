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

# Override keys:
#   engine, partition_by, primary_key, order_by, sample_by, ttl, settings
#     replace the argument of the same name; null clears it
#   drop_columns = ["name"], add_columns = [{...}], modify_columns = { name = {...} }
#   drop_indexes, add_indexes, drop_projections, add_projections, drop_constraints, add_constraints
#     the same, by name; to change one, drop it and add it
#   columns, indexes, projections, constraints
#     replace the whole list; the drop_ and add_ keys of the same list are then ignored
#   unmanaged_columns, unmanaged_indexes = ["regex"]
#     replace the argument of the same name
#   force_destroy = true
#     allow dropping or replacing the table while it holds rows; apply it on its own first
#   ignore_drop_dependencies = true
#     allow dropping or replacing the table while a dictionary or view reads from it
variable "node" {
  description = "The server the object lives on: { name, host, port, leader }. Null puts it on the provider's host."
  type        = any
  default     = null
}

variable "override" {
  description = "Changes to the definition for the target nodes."
  type        = any
  default     = {}
}

variable "engine" {
  description = "Engine expression."
  type        = string
}

variable "deployment" {
  description = "Kafka topic namespace for this environment."
  type = object({
    kafka_topic_prefix = optional(string, "")
    kafka_topic_suffix = optional(string, "")
  })
  default = {}
}

variable "partition_by" {
  type    = string
  default = null
}

variable "primary_key" {
  type    = string
  default = null
}

variable "order_by" {
  type    = string
  default = null
}

variable "sample_by" {
  type    = string
  default = null
}

variable "ttl" {
  type    = string
  default = null
}

variable "settings" {
  type    = string
  default = null
}

variable "columns" {
  type = list(object({
    name                    = string
    type                    = string
    default_expression      = optional(string)
    materialized_expression = optional(string)
    alias_expression        = optional(string)
    ephemeral_expression    = optional(string)
    codec                   = optional(string)
    ttl                     = optional(string)
    comment                 = optional(string)
  }))
}

variable "indexes" {
  type = list(object({
    name        = string
    expression  = string
    type        = string
    granularity = optional(number)
  }))
  default = []
}

variable "projections" {
  type = list(object({
    name     = string
    query    = string
    settings = optional(string)
  }))
  default = []
}

variable "constraints" {
  type = list(object({
    name  = string
    check = string
  }))
  default = []
}

variable "unmanaged_columns" {
  description = "Regexes. Columns on the node that match and are not declared are left alone: the app adds materialized columns at runtime."
  type        = list(string)
  default     = null
}

variable "unmanaged_indexes" {
  description = "Regexes. Indexes on the node that match and are not declared are left alone."
  type        = list(string)
  default     = null
}

locals {
  o = var.override

  drop_columns     = try(local.o.drop_columns, [])
  drop_indexes     = try(local.o.drop_indexes, [])
  drop_projections = try(local.o.drop_projections, [])
  drop_constraints = try(local.o.drop_constraints, [])

  columns = try(local.o.columns, concat(
    [for c in var.columns : try(local.o.modify_columns[c.name], c) if !contains(local.drop_columns, c.name)],
    try(local.o.add_columns, []),
  ))
  indexes = try(local.o.indexes, concat(
    [for i in var.indexes : i if !contains(local.drop_indexes, i.name)],
    try(local.o.add_indexes, []),
  ))
  projections = try(local.o.projections, concat(
    [for p in var.projections : p if !contains(local.drop_projections, p.name)],
    try(local.o.add_projections, []),
  ))
  constraints = try(local.o.constraints, concat(
    [for c in var.constraints : c if !contains(local.drop_constraints, c.name)],
    try(local.o.add_constraints, []),
  ))
}

locals {
  engine           = try(local.o.engine, var.engine)
  settings         = try(local.o.settings, var.settings)
  namespace_topics = (local.engine == "Kafka" || startswith(local.engine, "Kafka(")) && (var.deployment.kafka_topic_prefix != "" || var.deployment.kafka_topic_suffix != "")
  topic_lists      = regexall("kafka_topic_list\\s*=\\s*'([^']*)'", "${local.engine} ${coalesce(local.settings, " ")}")
  topics = length(local.topic_lists) == 0 ? [] : [
    for topic in split(",", local.topic_lists[0][0]) : "${var.deployment.kafka_topic_prefix}${trimspace(topic)}${var.deployment.kafka_topic_suffix}"
  ]
  topic_pattern = "/(kafka_topic_list\\s*=\\s*')[^']*'/"
  topic_value   = "$${1}${join(",", local.topics)}'"
}

resource "clickhousedbops_table" "this" {
  count = var.enabled ? 1 : 0

  database     = var.database
  name         = var.name
  engine       = local.namespace_topics ? replace(local.engine, local.topic_pattern, local.topic_value) : local.engine
  partition_by = try(local.o.partition_by, var.partition_by)
  primary_key  = try(local.o.primary_key, var.primary_key)
  order_by     = try(local.o.order_by, var.order_by)
  sample_by    = try(local.o.sample_by, var.sample_by)
  ttl          = try(local.o.ttl, var.ttl)
  settings     = local.settings == null ? null : local.namespace_topics ? replace(local.settings, local.topic_pattern, local.topic_value) : local.settings

  columns     = local.columns
  indexes     = length(local.indexes) > 0 ? local.indexes : null
  projections = length(local.projections) > 0 ? local.projections : null
  constraints = length(local.constraints) > 0 ? local.constraints : null

  unmanaged_columns = try(local.o.unmanaged_columns, var.unmanaged_columns)
  unmanaged_indexes = try(local.o.unmanaged_indexes, var.unmanaged_indexes)

  node = var.node == null ? null : { name = var.node.name, host = var.node.host, port = try(var.node.port, null) }
  # The shard's leader runs the ALTERs that Keeper replicates; the other replicas wait for them.
  replica_role = var.node != null && startswith(lower(local.engine), "replicated") ? (try(var.node.leader, true) ? "leader" : "follower") : null

  force_destroy            = try(local.o.force_destroy, false)
  ignore_drop_dependencies = try(local.o.ignore_drop_dependencies, false)

  lifecycle {
    precondition {
      condition     = !local.namespace_topics || length(local.topic_lists) == 1
      error_message = "Kafka topic namespaces require exactly one kafka_topic_list in the engine or settings."
    }
  }
}
