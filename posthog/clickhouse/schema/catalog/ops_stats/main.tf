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

module "event_property_daily_stats" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "event_property_daily_stats")
  database = var.database
  name     = "event_property_daily_stats"
  override = try(local.deployment.overrides["event_property_daily_stats"], {})
  engine   = "ReplicatedMergeTree('/clickhouse/ops/tables/{shard}/posthog.event_property_daily_stats', '{replica}')"
  order_by = "(analysis_date, team_id, property_key)"
  ttl      = "analysis_date + toIntervalDay(30)"
  settings = "index_granularity = 8192"
  columns = [
    { name = "analysis_date", type = "Date" },
    { name = "team_id", type = "Int64" },
    { name = "property_key", type = "String" },
    { name = "event_count", type = "UInt64" },
    { name = "distinct_event_names", type = "UInt32" },
    { name = "total_property_bytes", type = "UInt64" },
    { name = "min_property_bytes", type = "UInt64" },
    { name = "max_property_bytes", type = "UInt64" },
    { name = "avg_property_bytes", type = "Float64" },
    { name = "p50_property_bytes", type = "Float64" },
    { name = "p90_property_bytes", type = "Float64" },
    { name = "p95_property_bytes", type = "Float64" },
    { name = "p99_property_bytes", type = "Float64" },
    { name = "property_size_histogram", type = "Array(Tuple(Float64, Float64, UInt64))" },
    { name = "top_event_names", type = "Array(String)" },
    { name = "sample_rate", type = "Float32" },
    { name = "computed_at", type = "DateTime" },
  ]
}

module "query_team_daily_stats" {
  source = "../../lib/table"
  node   = var.node

  enabled      = contains(var.objects, "query_team_daily_stats")
  database     = var.database
  name         = "query_team_daily_stats"
  override     = try(local.deployment.overrides["query_team_daily_stats"], {})
  engine       = "ReplicatedMergeTree('/clickhouse/ops/tables/{shard}/posthog.query_team_daily_stats', '{replica}')"
  partition_by = "analysis_date"
  order_by     = "(analysis_date, team_id)"
  ttl          = "analysis_date + toIntervalDay(90)"
  settings     = "index_granularity = 8192"
  columns = [
    { name = "analysis_date", type = "Date" },
    { name = "team_id", type = "Int64" },
    { name = "query_count", type = "UInt64" },
    { name = "error_count", type = "UInt64" },
    { name = "distinct_query_shapes", type = "UInt64" },
    { name = "total_duration_ms", type = "UInt64" },
    { name = "avg_duration_ms", type = "Float64" },
    { name = "p50_duration_ms", type = "Float64" },
    { name = "p90_duration_ms", type = "Float64" },
    { name = "p99_duration_ms", type = "Float64" },
    { name = "max_duration_ms", type = "UInt64" },
    { name = "total_read_rows", type = "UInt64" },
    { name = "total_read_bytes", type = "UInt64", comment = "Uncompressed bytes scanned; initiator-folded (is_initial_query=1). Scan cost proxy, NOT stored footprint." },
    { name = "total_result_rows", type = "UInt64" },
    { name = "total_result_bytes", type = "UInt64" },
    { name = "total_written_rows", type = "UInt64" },
    { name = "total_written_bytes", type = "UInt64" },
    { name = "total_cpu_seconds", type = "Float64", comment = "OSCPUVirtualTimeMicroseconds summed across ALL shard rows / 1e6. CPU is not folded onto the initiator." },
    { name = "total_memory_usage", type = "UInt64", comment = "Peak memory summed across all shard rows." },
    { name = "max_memory_usage", type = "UInt64", comment = "Largest single-node peak across all shard rows." },
    { name = "p99_memory_usage", type = "Float64" },
    { name = "total_s3_get_objects", type = "UInt64", comment = "S3GetObject summed across all shard rows." },
    { name = "total_s3_read_bytes", type = "UInt64", comment = "ReadBufferFromS3Bytes summed across all shard rows." },
    { name = "query_kind_counts", type = "Map(String, UInt64)" },
    { name = "computed_at", type = "DateTime" },
  ]
}

module "s3_disk_orphan_prefixes" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "s3_disk_orphan_prefixes")
  database = var.database
  name     = "s3_disk_orphan_prefixes"
  override = try(local.deployment.overrides["s3_disk_orphan_prefixes"], {})
  query    = <<-SQL
    SELECT snapshot_date, prefix, hostname, total_objects AS object_count, total_stored_bytes AS total_bytes, min_oldest AS oldest_object, max_newest AS newest_object, dateDiff('day', max_newest, now()) AS days_since_newest FROM (SELECT snapshot_date, prefix, splitByChar('/', prefix)[2] AS hostname, sum(object_count) AS total_objects, sum(total_bytes) AS total_stored_bytes, min(oldest_object) AS min_oldest, max(newest_object) AS max_newest FROM ${var.database}.s3_disk_prefix_daily_stats WHERE (snapshot_date = (SELECT max(snapshot_date) FROM ${var.database}.s3_disk_prefix_daily_stats)) AND startsWith(prefix, 's3_mergetrees/') AND ((splitByChar('/', prefix)[2]) NOT IN (SELECT DISTINCT host_name FROM system.clusters)) GROUP BY snapshot_date, prefix)
  SQL
}

module "s3_disk_prefix_daily_stats" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "s3_disk_prefix_daily_stats")
  database = var.database
  name     = "s3_disk_prefix_daily_stats"
  override = try(local.deployment.overrides["s3_disk_prefix_daily_stats"], {})
  engine   = "ReplicatedMergeTree('/clickhouse/ops/tables/{shard}/posthog.s3_disk_prefix_daily_stats', '{replica}')"
  order_by = "(snapshot_date, prefix, storage_class)"
  ttl      = "snapshot_date + toIntervalDay(365)"
  settings = "index_granularity = 8192"
  columns = [
    { name = "snapshot_date", type = "Date", comment = "Date of the S3 Inventory report this row rolls up." },
    { name = "prefix", type = "String", comment = "For s3_mergetrees keys, first two segments (s3_mergetrees/<hostname>) so orphan detection can match the hostname against the live fleet; for other top-level prefixes in the shared bucket, just the first segment to avoid per-subkey fragmentation." },
    { name = "storage_class", type = "String" },
    { name = "object_count", type = "UInt64" },
    { name = "total_bytes", type = "UInt64", comment = "Sum of object sizes for this prefix/storage_class in the snapshot (stored footprint)." },
    { name = "oldest_object", type = "DateTime", comment = "min(last_modified) in the prefix; a stale max age is an orphan signal." },
    { name = "newest_object", type = "DateTime", comment = "max(last_modified) in the prefix." },
    { name = "computed_at", type = "DateTime" },
  ]
}

module "events_main" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "events_main")
  database = var.database
  name     = "events_main"
  override = try(local.deployment.overrides["events_main"], {})
  engine   = "Distributed('${var.database}', '${var.database}', 'sharded_events', sipHash64(distinct_id))"
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "String" },
    { name = "properties", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "elements_chain", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')" },
    { name = "person_id", type = "UUID" },
    { name = "person_created_at", type = "DateTime64(3)" },
    { name = "person_properties", type = "String" },
    { name = "group0_properties", type = "String" },
    { name = "group1_properties", type = "String" },
    { name = "group2_properties", type = "String" },
    { name = "group3_properties", type = "String" },
    { name = "group4_properties", type = "String" },
    { name = "group0_created_at", type = "DateTime64(3)" },
    { name = "group1_created_at", type = "DateTime64(3)" },
    { name = "group2_created_at", type = "DateTime64(3)" },
    { name = "group3_created_at", type = "DateTime64(3)" },
    { name = "group4_created_at", type = "DateTime64(3)" },
    { name = "person_mode", type = "Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "inserted_at", type = "DateTime64(6, 'UTC')" },
  ]
}
