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
  kafka_precalculated_person_properties_columns = [
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "UUID" },
    { name = "condition", type = "String" },
    { name = "matches", type = "Bool" },
    { name = "source", type = "String" },
  ]

  sharded_precalculated_person_properties_columns = concat(local.kafka_precalculated_person_properties_columns, [
    { name = "_timestamp", type = "DateTime64(6)" },
    { name = "_offset", type = "UInt64" },
  ])

  sharded_precalculated_events_columns = [
    { name = "team_id", type = "Int64" },
    { name = "date", type = "Date" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "UUID" },
    { name = "condition", type = "String" },
    { name = "uuid", type = "UUID" },
    { name = "source", type = "String" },
    { name = "_timestamp", type = "DateTime64(6)" },
    { name = "_partition", type = "UInt64" },
    { name = "_offset", type = "UInt64" },
  ]
}

module "sharded_precalculated_events_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "precalculated_events"
  database = var.database
  columns  = local.sharded_precalculated_events_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["_timestamp"]
    partition_by = "toYYYYMM(date)"
    order_by     = "(team_id, condition, date, distinct_id, uuid)"
  }
  sharding_key = "sipHash64(distinct_id)"
  kafka = {
    topic          = "clickhouse_prefiltered_events"
    consumer_group = "clickhouse_prefiltered_events"
    arguments      = "settings"
    columns = [
      { name = "team_id", type = "Int64" },
      { name = "date", type = "Nullable(Date)" },
      { name = "distinct_id", type = "String" },
      { name = "person_id", type = "UUID" },
      { name = "condition", type = "String" },
      { name = "uuid", type = "UUID" },
      { name = "source", type = "String" },
    ]
    settings = { kafka_flush_interval_ms = "7500", kafka_max_block_size = "1000000", kafka_num_consumers = "1", kafka_poll_max_batch_size = "100000", kafka_poll_timeout_ms = "1000", kafka_skip_broken_messages = "100" }
  }
  mv_select  = <<-SQL
team_id,
    ifNull(date, toDate(_timestamp)) AS date,
    distinct_id,
    person_id,
    condition,
    uuid,
    source,
    _timestamp,
    _offset,
    _partition
  SQL
  deployment = merge({ cluster = "posthog", kafka_collection = "msk_cluster" }, local.deployment)
}

module "sharded_precalculated_person_properties_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "precalculated_person_properties"
  database = var.database
  columns  = local.sharded_precalculated_person_properties_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["_timestamp"]
    order_by    = "(team_id, condition, distinct_id)"
  }
  sharding_key = "sipHash64(distinct_id)"
  kafka = {
    topic     = "clickhouse_precalculated_person_properties"
    arguments = "settings"
    columns   = local.kafka_precalculated_person_properties_columns
    settings  = { kafka_flush_interval_ms = "7500", kafka_max_block_size = "1000000", kafka_num_consumers = "1", kafka_poll_max_batch_size = "100000", kafka_poll_timeout_ms = "1000", kafka_skip_broken_messages = "100" }
  }
  mv_select  = <<-SQL
team_id,
    distinct_id,
    person_id,
    condition,
    matches,
    source,
    _timestamp,
    _offset
  SQL
  deployment = merge({ cluster = "posthog", kafka_collection = "msk_cluster" }, local.deployment)
}
