# Production objects from before this catalogue, declared from their live definitions. Only Cloud roots
# in posthog-cloud-infra list them.

variable "node" {
  type    = any
  default = null
}

variable "database" {
  type    = string
  default = "posthog"
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

module "metrics_exemplars" {
  source = "../../lib/table"
  node   = var.node

  enabled      = contains(var.objects, "metrics_exemplars")
  database     = var.database
  name         = "metrics_exemplars"
  override     = try(local.deployment.overrides["metrics_exemplars"], {})
  engine       = "ReplicatedMergeTree('/clickhouse/ops/tables/{shard}/posthog.metrics_exemplars', '{replica}')"
  partition_by = "toYYYYMMDD(timestamp)"
  order_by     = "(team_id, id, timestamp)"
  settings     = "index_granularity = 1024"
  columns = [
    { name = "team_id", type = "UInt64" },
    { name = "timestamp", type = "DateTime64(3, 'UTC')" },
    { name = "id", type = "UInt64" },
    { name = "value", type = "Float64" },
    { name = "labels_json", type = "String" },
  ]
}

module "metrics_histograms" {
  source = "../../lib/table"
  node   = var.node

  enabled      = contains(var.objects, "metrics_histograms")
  database     = var.database
  name         = "metrics_histograms"
  override     = try(local.deployment.overrides["metrics_histograms"], {})
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/ops/tables/{shard}/posthog.metrics_histograms', '{replica}', version)"
  partition_by = "toYYYYMMDD(timestamp)"
  order_by     = "(team_id, id, timestamp)"
  settings     = "index_granularity = 1024"
  columns = [
    { name = "team_id", type = "UInt64" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "timestamp", type = "DateTime64(3, 'UTC')" },
    { name = "id", type = "UInt64" },
    { name = "histogram", type = "String" },
    { name = "version", type = "UInt64" },
  ]
}

module "metrics_label_index" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "metrics_label_index")
  database = var.database
  name     = "metrics_label_index"
  override = try(local.deployment.overrides["metrics_label_index"], {})
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/ops/tables/{shard}/posthog.metrics_label_index', '{replica}')"
  order_by = "(team_id, metric_name, label_name, label_value, id)"
  settings = "index_granularity = 1024, deduplicate_merge_projection_mode = 'rebuild'"
  columns = [
    { name = "team_id", type = "UInt64" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "label_name", type = "LowCardinality(String)" },
    { name = "label_value", type = "String" },
    { name = "id", type = "UInt64" },
  ]
  projections = [
    { name = "by_label_value", query = "SELECT team_id, metric_name, label_name, label_value, id ORDER BY team_id, label_name, label_value, id, metric_name" },
    { name = "by_id_label", query = "SELECT team_id, metric_name, label_name, label_value, id ORDER BY team_id, id, label_name, metric_name, label_value" },
  ]
}

module "metrics_label_index_from_series_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "metrics_label_index_from_series_mv")
  database = var.database
  name     = "metrics_label_index_from_series_mv"
  override = try(local.deployment.overrides["metrics_label_index_from_series_mv"], {})
  to_table = "${var.database}.metrics_label_index"
  query    = <<-SQL
    SELECT team_id, metric_name, tupleElement(label_pair, 1) AS label_name, tupleElement(label_pair, 2) AS label_value, id FROM ${var.database}.metrics_series ARRAY JOIN JSONExtractKeysAndValues(labels_json, 'String') AS label_pair
  SQL
}

module "metrics_metadata" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "metrics_metadata")
  database = var.database
  name     = "metrics_metadata"
  override = try(local.deployment.overrides["metrics_metadata"], {})
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/ops/tables/{shard}/posthog.metrics_metadata', '{replica}', updated_at)"
  order_by = "(team_id, metric_family_name)"
  settings = "index_granularity = 1024"
  columns = [
    { name = "team_id", type = "UInt64" },
    { name = "metric_family_name", type = "LowCardinality(String)" },
    { name = "type", type = "LowCardinality(String)" },
    { name = "unit", type = "String" },
    { name = "help", type = "String" },
    { name = "updated_at", type = "DateTime64(3, 'UTC')" },
  ]
}

module "metrics_samples" {
  source = "../../lib/table"
  node   = var.node

  enabled      = contains(var.objects, "metrics_samples")
  database     = var.database
  name         = "metrics_samples"
  override     = try(local.deployment.overrides["metrics_samples"], {})
  engine       = "ReplicatedMergeTree('/clickhouse/ops/tables/{shard}/posthog.metrics_samples_new', '{replica}')"
  partition_by = "toYYYYMMDD(timestamp)"
  order_by     = "(team_id, metric_name, toStartOfTenMinutes(timestamp), id, timestamp)"
  settings     = "index_granularity = 8192"
  columns = [
    { name = "team_id", type = "UInt64", codec = "T64, Default" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "timestamp", type = "DateTime64(3, 'UTC')", codec = "DoubleDelta, Default" },
    { name = "id", type = "UInt64" },
    { name = "value", type = "Float64", codec = "Gorilla(8), Default" },
  ]
}

module "metrics_series" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "metrics_series")
  database = var.database
  name     = "metrics_series"
  override = try(local.deployment.overrides["metrics_series"], {})
  engine   = "ReplicatedMergeTree('/clickhouse/ops/tables/{shard}/posthog.metrics_series', '{replica}')"
  order_by = "(team_id, metric_name, id)"
  settings = "index_granularity = 1024"
  columns = [
    { name = "team_id", type = "UInt64" },
    { name = "id", type = "UInt64" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "labels_json", type = "String" },
    { name = "min_time", type = "DateTime64(3, 'UTC')" },
    { name = "max_time", type = "DateTime64(3, 'UTC')" },
  ]
  projections = [
    { name = "by_id", query = "SELECT team_id, id, metric_name, labels_json, min_time, max_time ORDER BY team_id, id" },
  ]
}
