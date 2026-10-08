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

locals {
}

# Column lists that more than one object uses.

locals {
  kafka_error_tracking_issue_fingerprint_overrides_columns = [
    { name = "team_id", type = "Int64" },
    { name = "fingerprint", type = "String" },
    { name = "issue_id", type = "UUID" },
    { name = "is_deleted", type = "Int8" },
    { name = "version", type = "Int64" },
  ]

  kafka_error_tracking_issue_fingerprint_embeddings_columns = [
    { name = "team_id", type = "Int64" },
    { name = "model_name", type = "LowCardinality(String)" },
    { name = "embedding_version", type = "Int64" },
    { name = "fingerprint", type = "String" },
    { name = "inserted_at", type = "DateTime64(3, 'UTC')" },
    { name = "embeddings", type = "Array(Float64)" },
  ]

  error_tracking_issue_fingerprint_overrides_columns = concat(local.kafka_error_tracking_issue_fingerprint_overrides_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])

  kafka_error_tracking_fingerprint_issue_state_columns = [
    { name = "team_id", type = "Int64" },
    { name = "fingerprint", type = "String" },
    { name = "issue_id", type = "UUID" },
    { name = "issue_name", type = "Nullable(String)" },
    { name = "issue_description", type = "Nullable(String)" },
    { name = "issue_status", type = "String" },
    { name = "issue_severity", type = "Nullable(String)" },
    { name = "assigned_user_id", type = "Nullable(Int64)" },
    { name = "assigned_role_id", type = "Nullable(UUID)" },
    { name = "first_seen", type = "DateTime64(3, 'UTC')" },
    { name = "is_deleted", type = "Int8" },
    { name = "version", type = "Int64" },
  ]

  raw_error_tracking_fingerprint_issue_state_columns = concat(local.kafka_error_tracking_fingerprint_issue_state_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])
}

module "error_tracking_issue_fingerprint_overrides_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "error_tracking_issue_fingerprint_overrides"
  database = var.database
  layout   = "global"
  columns  = local.error_tracking_issue_fingerprint_overrides_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["version"]
    order_by    = "(team_id, fingerprint)"
    settings    = "index_granularity = 512"
    indexes = [
      { name = "kafka_timestamp_minmax_error_tracking_issue_fingerprint_overrides", expression = "_timestamp", type = "minmax", granularity = 3 },
    ]
  }
  routing = {
    write = true
  }
  deployment = local.deployment
}

module "raw_error_tracking_fingerprint_issue_state_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "error_tracking_fingerprint_issue_state"
  database = var.database
  layout   = "global"
  columns  = local.raw_error_tracking_fingerprint_issue_state_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["version"]
    order_by    = "(team_id, fingerprint)"
    settings    = "index_granularity = 512"
    indexes = [
      { name = "kafka_timestamp_minmax_raw_error_tracking_fingerprint_issue_state", expression = "_timestamp", type = "minmax", granularity = 3 },
    ]
  }
  routing = {
    read = true
  }
  kafka = {
    topic          = "clickhouse_error_tracking_fingerprint_issue_state"
    consumer_group = "clickhouse-error-tracking-fingerprint-issue-state"
    arguments      = "settings"
    columns        = local.kafka_error_tracking_fingerprint_issue_state_columns
    settings       = {}
  }
  mv_select  = <<-SQL
team_id,
    fingerprint,
    issue_id,
    issue_name,
    issue_description,
    issue_status,
    issue_severity,
    assigned_user_id,
    assigned_role_id,
    first_seen,
    is_deleted,
    version,
    _timestamp,
    _offset,
    _partition
  SQL
  deployment = merge({ cluster = "aux", write_cluster = "aux", kafka_collection = "msk_cluster" }, local.deployment)
  names      = { storage = "raw_error_tracking_fingerprint_issue_state" }
}

# Distributed tables that inserts go through.


module "writable_error_tracking_issue_fingerprint_embeddings" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "writable_error_tracking_issue_fingerprint_embeddings")
  database = var.database
  name     = "writable_error_tracking_issue_fingerprint_embeddings"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'error_tracking_issue_fingerprint_embeddings')"
  columns = concat(local.kafka_error_tracking_issue_fingerprint_embeddings_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ])
  override = try(local.deployment.overrides["writable_error_tracking_issue_fingerprint_embeddings"], {})
}

# Kafka tables and the materialized views that consume them.


module "error_tracking_issue_fingerprint_embeddings_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "error_tracking_issue_fingerprint_embeddings_mv")
  database = var.database
  name     = "error_tracking_issue_fingerprint_embeddings_mv"
  to_table = "${var.database}.writable_error_tracking_issue_fingerprint_embeddings"
  query    = <<-SQL
    SELECT
        team_id,
        model_name,
        embedding_version,
        fingerprint,
        _timestamp AS inserted_at,
        embeddings,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_error_tracking_issue_fingerprint_embeddings
  SQL
  override = try(local.deployment.overrides["error_tracking_issue_fingerprint_embeddings_mv"], {})

  depends_on = [
    module.kafka_error_tracking_issue_fingerprint_embeddings,
    module.writable_error_tracking_issue_fingerprint_embeddings,
  ]
}

module "error_tracking_issue_fingerprint_overrides_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "error_tracking_issue_fingerprint_overrides_mv")
  database = var.database
  name     = "error_tracking_issue_fingerprint_overrides_mv"
  to_table = "${var.database}.writable_error_tracking_issue_fingerprint_overrides"
  query    = <<-SQL
    SELECT
        team_id,
        fingerprint,
        issue_id,
        is_deleted,
        version,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_error_tracking_issue_fingerprint_overrides
    WHERE version > 0
  SQL
  override = try(local.deployment.overrides["error_tracking_issue_fingerprint_overrides_mv"], {})

  depends_on = [
    module.kafka_error_tracking_issue_fingerprint_overrides,
    module.error_tracking_issue_fingerprint_overrides_family,
  ]
}


module "kafka_error_tracking_issue_fingerprint_embeddings" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_error_tracking_issue_fingerprint_embeddings")
  database = var.database
  name     = "kafka_error_tracking_issue_fingerprint_embeddings"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_error_tracking_fingerprint_embeddings', kafka_topic_list = 'clickhouse_error_tracking_issue_fingerprint_embeddings'"
  columns  = local.kafka_error_tracking_issue_fingerprint_embeddings_columns
  override = try(local.deployment.overrides["kafka_error_tracking_issue_fingerprint_embeddings"], {})
}

module "kafka_error_tracking_issue_fingerprint_overrides" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_error_tracking_issue_fingerprint_overrides")
  database = var.database
  name     = "kafka_error_tracking_issue_fingerprint_overrides"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse-error-tracking-issue-fingerprint-overrides', kafka_topic_list = 'clickhouse_error_tracking_issue_fingerprint'"
  columns  = local.kafka_error_tracking_issue_fingerprint_overrides_columns
  override = try(local.deployment.overrides["kafka_error_tracking_issue_fingerprint_overrides"], {})
}
