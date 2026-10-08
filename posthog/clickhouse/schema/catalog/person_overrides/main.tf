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

module "person_overrides_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "person_overrides"
  database = var.database
  layout   = "global"
  columns = [
    { name = "team_id", type = "Int32" },
    { name = "old_person_id", type = "UUID" },
    { name = "override_person_id", type = "UUID" },
    { name = "merged_at", type = "DateTime64(6, 'UTC')" },
    { name = "oldest_event", type = "DateTime64(6, 'UTC')" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "version", type = "Int32" },
  ]
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["version"]
    partition_by = "toYYYYMM(oldest_event)"
    order_by     = "(team_id, old_person_id)"
  }
  deployment = local.deployment
}

# Distributed tables, views and dictionaries that queries read from.

module "person_overrides_dict" {
  source = "../../lib/dictionary"
  node   = var.node

  enabled     = contains(var.objects, "person_overrides_dict")
  database    = var.database
  name        = "person_overrides_dict"
  primary_key = ["team_id", "old_person_id"]
  attributes = [
    { name = "team_id", type = "INT" },
    { name = "old_person_id", type = "UUID" },
    { name = "override_person_id", type = "UUID" },
  ]
  source_clause = "CLICKHOUSE(USER '${var.dictionary_user}'${local.dictionary_password_clause} QUERY '\\nSELECT\\n    team_id,\\n    old_person_id,\\n    argMax(override_person_id, version)\\nFROM\\n    `${var.database}`.`person_overrides` AS overrides\\nGROUP BY\\n    team_id,\\n    old_person_id\\n')"
  layout        = "COMPLEX_KEY_HASHED(PREALLOCATE 1)"
  lifetime      = "MIN 5 MAX 10"
  override      = try(local.deployment.overrides["person_overrides_dict"], {})

  depends_on = [
    module.person_overrides_family,
  ]
}

# Kafka tables and the materialized views that consume them.

module "kafka_person_overrides" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment
  enabled    = contains(var.objects, "kafka_person_overrides")
  database   = var.database
  name       = "kafka_person_overrides"
  engine     = "Kafka"
  settings   = "kafka_broker_list = 'kafka:9092', kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse-person-overrides', kafka_topic_list = 'clickhouse_person_override'"
  columns = [
    { name = "team_id", type = "Int32" },
    { name = "old_person_id", type = "UUID" },
    { name = "override_person_id", type = "UUID" },
    { name = "merged_at", type = "DateTime64(6, 'UTC')" },
    { name = "oldest_event", type = "DateTime64(6, 'UTC')" },
    { name = "version", type = "Int32" },
  ]
  override = try(local.deployment.overrides["kafka_person_overrides"], {})
}

module "person_overrides_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "person_overrides_mv")
  database = var.database
  name     = "person_overrides_mv"
  to_table = "${var.database}.person_overrides"
  query    = <<-SQL
    SELECT
        team_id,
        old_person_id,
        override_person_id,
        merged_at,
        oldest_event,
        version
    FROM ${var.database}.kafka_person_overrides
  SQL
  override = try(local.deployment.overrides["person_overrides_mv"], {})

  depends_on = [
    module.kafka_person_overrides,
    module.person_overrides_family,
  ]
}
