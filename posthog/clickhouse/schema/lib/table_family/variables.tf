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
  description = "Expression used for routing inserts and Distributed reads."
  type        = string
  default     = "cityHash64(team_id)"
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
    settings       = optional(map(string))
  })
  default = null
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

variable "deployment" {
  description = "Placement and operational differences supplied by the calling root. Keeper paths are complete paths, never suffixes."
  type = object({
    components       = set(string)
    cluster          = string
    read_cluster     = optional(string)
    write_cluster    = optional(string)
    kafka_collection = optional(string, "warpstream_ingestion")
    kafka_settings   = optional(map(string), {})
    keeper_path      = optional(string)
    replica_name     = optional(string)
    exclude          = optional(set(string), [])
    overrides        = optional(any, {})
  })
  validation {
    condition     = length(setsubtract(var.deployment.components, ["storage", "read", "write", "ingest"])) == 0
    error_message = "Unknown table-family component. Use storage, read, write or ingest."
  }
  validation {
    condition = alltrue([for name, override in var.deployment.overrides :
      name == coalesce(var.names.storage, var.layout == "sharded" ? "sharded_${var.name}" : var.name) ||
      length(setintersection(keys(override), ["indexes", "add_indexes", "drop_indexes", "projections", "add_projections", "drop_projections", "constraints", "add_constraints", "drop_constraints"])) == 0
    ])
    error_message = "Indexes, projections and constraints can only be overridden on the storage table."
  }
  validation {
    condition = alltrue([for name, override in var.deployment.overrides :
      name == coalesce(var.names.storage, var.layout == "sharded" ? "sharded_${var.name}" : var.name) ||
      alltrue([for column in concat(try(override.add_columns, []), try(values(override.modify_columns), [])) :
        alltrue([for attribute in ["codec", "ttl", "materialized_expression", "ephemeral_expression"] : try(column[attribute], null) == null])
      ])
    ])
    error_message = "Column codecs, TTLs and computed expressions can only be overridden on the storage table."
  }

}
