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

# Column lists that more than one object uses.

locals {
  kafka_person_distinct_id2_columns = [
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "UUID" },
    { name = "is_deleted", type = "Int8" },
    { name = "version", type = "Int64" },
  ]

  person_distinct_id2_columns = concat(local.kafka_person_distinct_id2_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])
}

module "person_distinct_id_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "person_distinct_id"
  database = var.database
  layout   = "global"
  columns = [
    { name = "distinct_id", type = "String", comment = "skip_0003_fill_person_distinct_id2" },
    { name = "person_id", type = "UUID" },
    { name = "team_id", type = "Int64" },
    { name = "_sign", type = "Int8", default_expression = "1" },
    { name = "is_deleted", type = "Int8", alias_expression = "if(_sign = -1, 1, 0)" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ]
  storage = {
    engine      = "CollapsingMergeTree"
    engine_args = ["_sign"]
    order_by    = "(team_id, distinct_id, person_id)"
  }
  routing = {
    write = false
  }
  kafka = {
    topic          = "clickhouse_person_unique_id"
    consumer_group = "group1"
    arguments      = "settings"
    columns = [
      { name = "distinct_id", type = "String" },
      { name = "person_id", type = "UUID" },
      { name = "team_id", type = "Int64" },
      { name = "_sign", type = "Nullable(Int8)" },
      { name = "is_deleted", type = "Nullable(Int8)" },
    ]
    settings = {}
  }
  mv_select  = <<-SQL
distinct_id,
    person_id,
    team_id,
    coalesce(_sign, if(is_deleted = 0, 1, -1)) AS _sign,
    _timestamp,
    _offset
  SQL
  mv_target  = "${var.database}.person_distinct_id"
  deployment = merge({ kafka_collection = "msk_cluster" }, local.deployment)
}

module "person_distinct_id2_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "person_distinct_id2"
  database = var.database
  layout   = "global"
  columns  = local.person_distinct_id2_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["version"]
    order_by    = "(team_id, distinct_id)"
    settings    = "index_granularity = 512"
    indexes = [
      { name = "kafka_timestamp_minmax_person_distinct_id2", expression = "_timestamp", type = "minmax", granularity = 3 },
    ]
  }
  kafka = {
    topic          = "clickhouse_person_distinct_id"
    consumer_group = "group1"
    arguments      = "settings"
    columns        = local.kafka_person_distinct_id2_columns
    settings       = {}
  }
  mv_select  = <<-SQL
team_id,
    distinct_id,
    person_id,
    is_deleted,
    version,
    _timestamp,
    _offset,
    _partition
  SQL
  deployment = merge({ kafka_collection = "msk_cluster" }, local.deployment)
}
