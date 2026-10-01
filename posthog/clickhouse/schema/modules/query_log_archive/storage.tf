# Tables that hold data, and the materialized views between them.

module "ops_query_log_archive_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "ops_query_log_archive_mv")
  database = var.database
  name     = "ops_query_log_archive_mv"
  to_table = "${var.database}.writable_query_log_archive"
  query    = <<-SQL
    SELECT
        hostname,
        user,
        query_id,
        initial_query_id,
        is_initial_query,
        type,
        event_date,
        event_time,
        event_time_microseconds,
        query_start_time,
        query_start_time_microseconds,
        query_duration_ms,
        read_rows,
        read_bytes,
        written_rows,
        written_bytes,
        result_rows,
        result_bytes,
        memory_usage,
        peak_threads_usage,
        current_database,
        query,
        formatted_query,
        normalized_query_hash,
        query_kind,
        exception_code,
        exception,
        stack_trace,
        JSONExtractInt(log_comment, 'team_id') AS team_id,
        if(isValidJSON(log_comment), log_comment, '{}') AS log_comment,
        ProfileEvents
    FROM system.query_log
    WHERE type != 'QueryStart'
  SQL
  override = try(var.overrides["ops_query_log_archive_mv"], {})

  depends_on = [
    module.writable_query_log_archive,
  ]
}

module "query_log_archive_buffer" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "query_log_archive_buffer")
  database = var.database
  name     = "query_log_archive_buffer"
  engine   = "Buffer('posthog', 'sharded_query_log_archive', 16, 10, 60, 10000, 1000000, 10000000, 100000000)"
  columns  = local.query_log_archive_buffer_columns
  override = try(var.overrides["query_log_archive_buffer"], {})
}

module "query_log_archive_v2" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "query_log_archive_v2")
  database     = var.database
  name         = "query_log_archive_v2"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.query_log_archive_new${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toYYYYMM(event_date)"
  order_by     = "(team_id, event_date, event_time, query_id)"
  columns      = local.query_log_archive_v2_columns
  override     = try(var.overrides["query_log_archive_v2"], {})
}

module "sharded_query_log_archive" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_query_log_archive")
  database     = var.database
  name         = "sharded_query_log_archive"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.sharded_query_log_archive${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toYYYYMM(event_date)"
  order_by     = "(team_id, event_date, event_time, query_id)"
  settings     = "index_granularity = 8192, object_serialization_version = 'v3', object_shared_data_serialization_version = 'map_with_buckets'"
  columns      = local.sharded_query_log_archive_columns
  override     = try(var.overrides["sharded_query_log_archive"], {})
}

module "sharded_query_log_archive_old" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_query_log_archive_old")
  database     = var.database
  name         = "sharded_query_log_archive_old"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/{shard}/posthog.sharded_query_log_archive${var.zk_path_suffix}', '{replica}')"
  partition_by = "toYYYYMM(event_date)"
  order_by     = "(team_id, event_date, event_time, query_id)"
  columns      = local.query_log_archive_v2_columns
  override     = try(var.overrides["sharded_query_log_archive_old"], {})
}
