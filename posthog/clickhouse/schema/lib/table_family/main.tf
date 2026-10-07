variable "node" {
  description = "The server the object lives on: { name, host, port, leader }. Null puts it on the provider's host."
  type        = any
  default     = null
}

variable "name" {
  description = "Logical family name. Standard object names are derived from it."
  type        = string
}

variable "database" {
  type    = string
  default = "posthog"
}

variable "layout" {
  description = "Sharded data with Distributed readers, or one global replication group."
  type        = string
  default     = "sharded"
  validation {
    condition     = contains(["sharded", "global"], var.layout)
    error_message = "layout must be sharded or global."
  }
}

variable "columns" {
  description = "Stored columns. Physical attributes stay on the storage table."
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

variable "storage" {
  type = object({
    engine       = optional(string, "MergeTree")
    replicated   = optional(bool, true)
    engine_args  = optional(list(string), [])
    order_by     = string
    partition_by = optional(string)
    primary_key  = optional(string)
    sample_by    = optional(string)
    ttl          = optional(string)
    settings     = optional(string)
    indexes = optional(list(object({
      name = string, expression = string, type = string, granularity = optional(number)
    })), [])
    projections = optional(list(object({
      name = string, query = string, settings = optional(string)
    })), [])
    constraints       = optional(list(object({ name = string, check = string })), [])
    unmanaged_columns = optional(list(string))
    unmanaged_indexes = optional(list(string))
  })
  validation {
    condition     = contains(["MergeTree", "ReplacingMergeTree", "AggregatingMergeTree", "SummingMergeTree", "CollapsingMergeTree", "VersionedCollapsingMergeTree"], var.storage.engine)
    error_message = "storage.engine must be an unreplicated MergeTree engine; replication is supplied by the library."
  }
}

variable "sharding_key" {
  description = "Routing expression. Null uses the layout's default; an empty string omits the sharding argument."
  type        = string
  default     = null
}

variable "routing" {
  description = "Explicit routing objects and schemas for existing families that differ from the convention."
  type = object({
    read          = optional(bool)
    write         = optional(bool)
    read_columns  = optional(any)
    write_columns = optional(any)
  })
  default = {}
}

variable "kafka" {
  description = "Input schema and topic. Null leaves out Kafka and its materialized view. Settings, when supplied, replace the standard consumer settings."
  type = object({
    topic = string
    columns = list(object({
      name             = string
      type             = string
      alias_expression = optional(string)
      comment          = optional(string)
    }))
    consumer_group = optional(string)
    format         = optional(string, "JSONEachRow")
    arguments      = optional(string, "engine")
    settings       = optional(map(string))
  })
  default = null
  validation {
    condition     = var.kafka == null ? true : contains(["engine", "settings"], var.kafka.arguments)
    error_message = "Kafka arguments must use engine or settings syntax."
  }
}

variable "mv_target" {
  description = "Existing ingestion target when it is not the conventional writable table."
  type        = string
  default     = null
}

variable "mv_select" {
  description = "SELECT expressions for the Kafka materialized view; the library supplies FROM and TO."
  type        = string
  default     = null
  validation {
    condition     = var.kafka == null ? var.mv_select == null : var.mv_select != null
    error_message = "A Kafka input requires mv_select, and mv_select requires a Kafka input."
  }
}

variable "names" {
  description = "Explicit names for existing objects that do not use the naming convention."
  type = object({
    storage = optional(string)
    read    = optional(string)
    write   = optional(string)
    kafka   = optional(string)
    mv      = optional(string)
  })
  default = {}
}

variable "objects" {
  description = "Names of the objects to create. A name that is not one of this family's objects is ignored."
  type        = set(string)
}

variable "deployment" {
  description = "Operational differences supplied by the calling root. Keeper paths are complete paths, never suffixes."
  type = object({
    cluster            = optional(string)
    read_cluster       = optional(string)
    write_cluster      = optional(string)
    kafka_collection   = optional(string, "warpstream_ingestion")
    kafka_settings     = optional(map(string), {})
    kafka_topic_prefix = optional(string, "")
    kafka_topic_suffix = optional(string, "")
    keeper_path        = optional(string)
    replica_name       = optional(string)
    overrides          = optional(any, {})
  })
  default = {}
  validation {
    condition = alltrue([for name, override in var.deployment.overrides :
      name == coalesce(var.names.storage, var.layout == "sharded" ? "sharded_${var.name}" : var.name) ||
      can(regex("^(Replicated)?[A-Za-z]*MergeTree", try(override.engine, ""))) ||
      length(setintersection(keys(override), ["indexes", "add_indexes", "drop_indexes", "projections", "add_projections", "drop_projections", "constraints", "add_constraints", "drop_constraints"])) == 0
      if contains(values(local.names), name)
    ])
    error_message = "Indexes, projections and constraints can only be overridden on a MergeTree storage table."
  }
  validation {
    condition = alltrue([for name, override in var.deployment.overrides :
      name == coalesce(var.names.storage, var.layout == "sharded" ? "sharded_${var.name}" : var.name) ||
      can(regex("^(Replicated)?[A-Za-z]*MergeTree", try(override.engine, ""))) ||
      alltrue([for column in concat(try(override.add_columns, []), try(values(override.modify_columns), [])) :
        alltrue([for attribute in ["codec", "ttl"] : try(column[attribute], null) == null])
      ])
      if contains(values(local.names), name)
    ])
    error_message = "Column codecs and TTLs can only be overridden on a MergeTree storage table."
  }

}

locals {
  names = {
    storage = coalesce(var.names.storage, var.layout == "sharded" ? "sharded_${var.name}" : var.name)
    read    = coalesce(var.names.read, var.name)
    write   = coalesce(var.names.write, "writable_${var.name}")
    kafka   = coalesce(var.names.kafka, "kafka_${var.name}")
    mv      = coalesce(var.names.mv, "${var.name}_mv")
  }
  cluster   = coalesce(var.deployment.cluster, var.layout == "global" ? "posthog" : "aux")
  overrides = { for name, override in var.deployment.overrides : name => override if contains(values(local.names), name) }
  enabled = {
    storage = contains(var.objects, local.names.storage)
    read    = coalesce(var.routing.read, var.layout == "sharded") && contains(var.objects, local.names.read)
    write   = coalesce(var.routing.write, var.layout == "sharded" || var.kafka != null) && contains(var.objects, local.names.write)
    kafka   = var.kafka != null && contains(var.objects, local.names.kafka)
    mv      = var.kafka != null && contains(var.objects, local.names.mv)
  }
  keeper_path = coalesce(var.deployment.keeper_path,
    var.layout == "sharded" ? "/clickhouse/tables/{shard}/${var.database}.${local.names.storage}" : "/clickhouse/tables/noshard/${var.database}.${local.names.storage}"
  )
  replica_name = coalesce(var.deployment.replica_name, var.layout == "sharded" ? "{replica}" : "{replica}-{shard}")
  engine_args  = length(var.storage.engine_args) == 0 ? "" : ", ${join(", ", var.storage.engine_args)}"
  read_cluster = coalesce(var.deployment.read_cluster, local.cluster)
  write_cluster = coalesce(var.deployment.write_cluster,
    var.layout == "global" ? "${local.cluster}_single_shard" : local.cluster
  )
  sharding_key = var.sharding_key == null ? (var.layout == "global" ? "" : "cityHash64(team_id)") : var.sharding_key
  sharding_arg = local.sharding_key == "" ? "" : ", ${local.sharding_key}"

  # Computed values are read as plain columns; only storage computes and compresses them.
  read_columns = [for column in var.columns : {
    name               = column.name, type = column.type,
    default_expression = column.default_expression, comment = column.comment
  }]
  write_columns = [for column in var.columns : {
    name               = column.name, type = column.type,
    default_expression = column.default_expression, comment = column.comment
  } if column.materialized_expression == null && column.alias_expression == null && column.ephemeral_expression == null]

  kafka_group = var.kafka == null ? "" : coalesce(var.kafka.consumer_group, "clickhouse_${var.name}")
  kafka_settings = var.kafka == null ? {} : merge(var.kafka.settings == null ? {
    kafka_max_block_size       = "100000"
    kafka_num_consumers        = "1"
    kafka_poll_timeout_ms      = "10000"
    kafka_skip_broken_messages = "100"
    kafka_thread_per_consumer  = "1"
  } : var.kafka.settings, var.deployment.kafka_settings)
  kafka_arguments = var.kafka == null ? {} : {
    kafka_topic_list = "'${var.kafka.topic}'"
    kafka_group_name = "'${local.kafka_group}'"
    kafka_format     = "'${var.kafka.format}'"
  }
  kafka_engine            = var.kafka == null ? "Kafka" : var.kafka.arguments == "settings" ? "Kafka(${var.deployment.kafka_collection})" : "Kafka(${var.deployment.kafka_collection}, kafka_topic_list = '${var.kafka.topic}', kafka_group_name = '${local.kafka_group}', kafka_format = '${var.kafka.format}')"
  resolved_kafka_settings = merge(local.kafka_settings, var.kafka == null ? {} : var.kafka.arguments == "settings" ? local.kafka_arguments : {})
}

module "storage" {
  source = "../table"
  node   = var.node

  enabled           = local.enabled.storage
  database          = var.database
  name              = local.names.storage
  engine            = var.storage.replicated ? "Replicated${var.storage.engine}('${local.keeper_path}', '${local.replica_name}'${local.engine_args})" : "${var.storage.engine}${length(var.storage.engine_args) == 0 ? "" : "(${join(", ", var.storage.engine_args)})"}"
  columns           = var.columns
  partition_by      = var.storage.partition_by
  primary_key       = var.storage.primary_key
  order_by          = var.storage.order_by
  sample_by         = var.storage.sample_by
  ttl               = var.storage.ttl
  settings          = var.storage.settings
  indexes           = var.storage.indexes
  projections       = var.storage.projections
  constraints       = var.storage.constraints
  unmanaged_columns = var.storage.unmanaged_columns
  unmanaged_indexes = var.storage.unmanaged_indexes
  override          = try(local.overrides[local.names.storage], {})
}

module "read" {
  source = "../table"
  node   = var.node

  enabled    = local.enabled.read
  database   = var.database
  name       = local.names.read
  engine     = "Distributed('${local.read_cluster}', '${var.database}', '${local.names.storage}'${local.sharding_arg})"
  columns    = var.routing.read_columns == null ? local.read_columns : var.routing.read_columns
  override   = try(local.overrides[local.names.read], {})
  depends_on = [module.storage]
}

module "write" {
  source = "../table"
  node   = var.node

  enabled    = local.enabled.write
  database   = var.database
  name       = local.names.write
  engine     = "Distributed('${local.write_cluster}', '${var.database}', '${local.names.storage}'${local.sharding_arg})"
  columns    = var.routing.write_columns == null ? local.write_columns : var.routing.write_columns
  override   = try(local.overrides[local.names.write], {})
  depends_on = [module.storage]
}

module "kafka" {
  source = "../table"
  node   = var.node

  deployment = var.deployment

  enabled    = local.enabled.kafka
  database   = var.database
  name       = local.names.kafka
  engine     = local.kafka_engine
  columns    = var.kafka == null ? [] : var.kafka.columns
  settings   = length(local.resolved_kafka_settings) == 0 ? null : join(", ", [for key in sort(keys(local.resolved_kafka_settings)) : "${key} = ${local.resolved_kafka_settings[key]}"])
  override   = try(local.overrides[local.names.kafka], {})
  depends_on = [module.write]
}

module "mv" {
  source  = "../materialized_view"
  node    = var.node
  objects = var.objects

  enabled    = local.enabled.mv
  database   = var.database
  name       = local.names.mv
  to_table   = coalesce(var.mv_target, "${var.database}.${local.names.write}")
  query      = var.kafka == null ? "SELECT 1" : "SELECT ${var.mv_select} FROM ${var.database}.${local.names.kafka}"
  override   = try(local.overrides[local.names.mv], {})
  depends_on = [module.kafka, module.write, module.storage, module.read]
}

output "objects" {
  description = "Enabled objects for adoption tooling. No credentials are included."
  value = { for kind, enabled in local.enabled : kind => {
    id   = "${var.database}.${local.names[kind]}"
    name = local.names[kind]
    type = kind == "mv" ? "clickhousedbops_materialized_view" : "clickhousedbops_table"
  } if enabled }
  precondition {
    condition     = !local.enabled.mv || (local.enabled.kafka && (var.mv_target != null || local.enabled.write))
    error_message = "An ingestion materialized view requires its Kafka source and writable target on the same root."
  }
}
