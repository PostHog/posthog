# Kafka tables and the materialized views that consume them.

module "hog_invocation_results_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "hog_invocation_results_mv")
  database = var.database
  name     = "hog_invocation_results_mv"
  to_table = "${var.database}.hog_invocation_results_data"
  query    = <<-SQL
    SELECT
        team_id,
        function_kind,
        function_id,
        invocation_id,
        parent_run_id,
        status,
        attempts,
        is_retry,
        scheduled_at,
        if(first_scheduled_at = toDateTime64('1970-01-01 00:00:00', 6, 'UTC'), scheduled_at, first_scheduled_at) AS first_scheduled_at,
        started_at,
        finished_at,
        duration_ms,
        error_kind,
        error_message,
        event_uuid,
        distinct_id,
        person_id,
        invocation_globals,
        version,
        is_deleted,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_hog_invocation_results
  SQL
  override = try(var.overrides["hog_invocation_results_mv"], {})

  depends_on = [
    module.hog_invocation_results_data,
    module.kafka_hog_invocation_results,
  ]
}

module "kafka_hog_invocation_results" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_hog_invocation_results")
  database = var.database
  name     = "kafka_hog_invocation_results"
  engine   = "Kafka(warpstream_cyclotron)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_hog_invocation_results', kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_hog_invocation_results'"
  columns  = local.kafka_hog_invocation_results_columns
  override = try(var.overrides["kafka_hog_invocation_results"], {})
}
