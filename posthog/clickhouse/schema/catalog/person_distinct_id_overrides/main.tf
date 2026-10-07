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

locals {

  # A dictionary source has no PASSWORD clause when the user has no password.
  dictionary_password_clause = var.dictionary_password == "" ? "" : " PASSWORD '${var.dictionary_password}'"
}

# Column lists that more than one object uses.

locals {
  kafka_person_distinct_id_overrides_columns = [
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "UUID" },
    { name = "is_deleted", type = "Int8" },
    { name = "version", type = "Int64" },
  ]

  person_distinct_id_overrides_columns = concat(local.kafka_person_distinct_id_overrides_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])
}

module "person_distinct_id_overrides_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "person_distinct_id_overrides"
  database = var.database
  layout   = "global"
  columns  = local.person_distinct_id_overrides_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["version"]
    order_by    = "(team_id, distinct_id)"
    settings    = "index_granularity = 512"
    indexes = [
      { name = "kafka_timestamp_minmax_person_distinct_id_overrides", expression = "_timestamp", type = "minmax", granularity = 3 },
    ]
  }
  routing = {
    write = true
  }
  deployment = local.deployment
}

# Distributed tables, views and dictionaries that queries read from.

module "person_distinct_id_overrides_dict" {
  source = "../../lib/dictionary"
  node   = var.node

  enabled     = contains(var.objects, "person_distinct_id_overrides_dict")
  database    = var.database
  name        = "person_distinct_id_overrides_dict"
  primary_key = ["team_id", "distinct_id"]
  attributes = [
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "UUID" },
  ]
  source_clause = "CLICKHOUSE(USER '${var.dictionary_user}'${local.dictionary_password_clause} QUERY 'SELECT team_id, distinct_id, argMax(person_id, version) AS person_id FROM ${var.database}.person_distinct_id_overrides GROUP BY team_id, distinct_id')"
  layout        = "COMPLEX_KEY_HASHED()"
  lifetime      = "MIN 3600 MAX 18000"
  override      = try(local.deployment.overrides["person_distinct_id_overrides_dict"], {})

  depends_on = [
    module.person_distinct_id_overrides_family,
  ]
}

# Kafka tables and the materialized views that consume them.

module "kafka_person_distinct_id_overrides" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_person_distinct_id_overrides")
  database = var.database
  name     = "kafka_person_distinct_id_overrides"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse-person-distinct-id-overrides', kafka_topic_list = 'clickhouse_person_distinct_id'"
  columns  = local.kafka_person_distinct_id_overrides_columns
  override = try(local.deployment.overrides["kafka_person_distinct_id_overrides"], {})
}

module "person_distinct_id_overrides_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "person_distinct_id_overrides_mv")
  database = var.database
  name     = "person_distinct_id_overrides_mv"
  to_table = "${var.database}.writable_person_distinct_id_overrides"
  query    = <<-SQL
    SELECT
        team_id,
        distinct_id,
        person_id,
        is_deleted,
        version,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_person_distinct_id_overrides
    WHERE version > 0
  SQL
  override = try(local.deployment.overrides["person_distinct_id_overrides_mv"], {})

  depends_on = [
    module.kafka_person_distinct_id_overrides,
    module.person_distinct_id_overrides_family,
  ]
}
