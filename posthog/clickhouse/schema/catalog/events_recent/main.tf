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

variable "ttl" {
  description = "Set table TTLs. Tests turn them off, because they insert rows with old timestamps."
  type        = bool
  default     = true
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

# Reads from events. Those must exist on the node first.

locals {
}

# Column lists that more than one object uses.

locals {
  writable_events_recent_columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "String" },
    { name = "properties", type = "String", codec = "ZSTD(3)" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "elements_chain", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')" },
    { name = "person_id", type = "UUID" },
    { name = "person_created_at", type = "DateTime64(3)" },
    { name = "person_properties", type = "String", codec = "ZSTD(3)" },
    { name = "group0_properties", type = "String", codec = "ZSTD(3)" },
    { name = "group1_properties", type = "String", codec = "ZSTD(3)" },
    { name = "group2_properties", type = "String", codec = "ZSTD(3)" },
    { name = "group3_properties", type = "String", codec = "ZSTD(3)" },
    { name = "group4_properties", type = "String", codec = "ZSTD(3)" },
    { name = "group0_created_at", type = "DateTime64(3)" },
    { name = "group1_created_at", type = "DateTime64(3)" },
    { name = "group2_created_at", type = "DateTime64(3)" },
    { name = "group3_created_at", type = "DateTime64(3)" },
    { name = "group4_created_at", type = "DateTime64(3)" },
    { name = "person_mode", type = "Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)" },
    { name = "historical_migration", type = "Bool" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ]

  sharded_events_recent_columns = concat(local.writable_events_recent_columns, [
    { name = "inserted_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
  ])
}

module "sharded_events_recent_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "distributed_events_recent"
  database = var.database
  columns  = local.sharded_events_recent_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["_timestamp"]
    partition_by = "toStartOfDay(inserted_at)"
    order_by     = "(team_id, toStartOfHour(inserted_at), event, cityHash64(distinct_id), cityHash64(uuid))"
    ttl          = var.ttl ? "toDate(inserted_at) + toIntervalDay(9)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    read_columns  = local.sharded_events_recent_columns
    write_columns = local.writable_events_recent_columns
  }
  sharding_key = "sipHash64(distinct_id)"
  deployment   = merge({ cluster = "posthog_writable", read_cluster = "posthog_primary_replica" }, local.deployment)
  names        = { storage = "sharded_events_recent", write = "writable_events_recent" }
}

# Tables that hold data, and the materialized views between them.

module "events_recent_json_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "events_recent_json_mv")
  database = var.database
  name     = "events_recent_json_mv"
  to_table = "${var.database}.writable_events_recent"
  query    = <<-SQL
    SELECT
        uuid,
        event,
        properties,
        timestamp,
        team_id,
        distinct_id,
        elements_chain,
        created_at,
        person_id,
        person_created_at,
        person_properties,
        group0_properties,
        group1_properties,
        group2_properties,
        group3_properties,
        group4_properties,
        group0_created_at,
        group1_created_at,
        group2_created_at,
        group3_created_at,
        group4_created_at,
        person_mode,
        _timestamp,
        _offset
    FROM ${var.database}.sharded_events
  SQL
  override = try(local.deployment.overrides["events_recent_json_mv"], {})

  depends_on = [
    module.sharded_events_recent_family,
  ]
}

# Distributed tables, views and dictionaries that queries read from.


module "events_batch_export_recent" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "events_batch_export_recent")
  database = var.database
  name     = "events_batch_export_recent"
  query    = <<-SQL
    SELECT
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        inserted_at AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM ${var.database}.events_recent
    PREWHERE (events_recent.inserted_at >= {interval_start:DateTime64}) AND (events_recent.inserted_at < {interval_end:DateTime64})
    WHERE (team_id = {team_id:Int64}) AND ((length({include_events:Array(String)}) = 0) OR (event IN ({include_events:Array(String)}))) AND ((length({exclude_events:Array(String)}) = 0) OR (event NOT IN ({exclude_events:Array(String)})))
    ORDER BY
        _inserted_at ASC,
        event ASC
    LIMIT 1 BY
        team_id,
        event,
        cityHash64(events_recent.distinct_id),
        cityHash64(events_recent.uuid)
    SETTINGS optimize_aggregation_in_order = 1
  SQL
  override = try(local.deployment.overrides["events_batch_export_recent"], {})

  depends_on = [
    module.events_recent,
  ]
}

module "events_recent" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "events_recent")
  database = var.database
  name     = "events_recent"
  engine   = "Distributed('posthog_primary_replica', '${var.database}', 'sharded_events_recent', sipHash64(distinct_id))"
  columns  = local.sharded_events_recent_columns
  override = try(local.deployment.overrides["events_recent"], {})
}
