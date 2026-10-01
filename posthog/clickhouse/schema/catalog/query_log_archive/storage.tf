# Tables that hold data, and the materialized views between them.

module "ops_query_log_archive_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "ops_query_log_archive_mv")
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
  override = try(local.deployment.overrides["ops_query_log_archive_mv"], {})

  depends_on = [
    module.writable_query_log_archive,
  ]
}

module "query_log_archive_buffer" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(local.deployment.exclude, "query_log_archive_buffer")
  database = var.database
  name     = "query_log_archive_buffer"
  engine   = "Buffer('posthog', 'sharded_query_log_archive', 16, 10, 60, 10000, 1000000, 10000000, 100000000)"
  columns  = local.query_log_archive_buffer_columns
  override = try(local.deployment.overrides["query_log_archive_buffer"], {})
}
