locals {
  deployment_defaults = merge({
    kafka_topic_prefix = var.kafka_topic_prefix
    kafka_topic_suffix = var.test ? "_test" : ""
  }, var.keeper_path == null ? {} : { keeper_path = var.keeper_path })

  # Runtime materialization starts from the same empty state as the existing test schema.
  test_overrides = {
    sharded_events = {
      drop_columns = ["mat_$ai_trace_id", "mat_$ai_session_id", "mat_$ai_is_error", "mat_$ai_prompt_name", "mat_$ai_experiment_id"]
      drop_indexes = ["bloom_filter_$ai_trace_id", "bloom_filter_$ai_session_id", "minmax_$ai_session_id", "set_$ai_is_error", "bloom_filter_$ai_prompt_name", "minmax_$ai_prompt_name", "bloom_filter_$ai_experiment_id", "minmax_$ai_experiment_id"]
    }
    events = {
      drop_columns = ["mat_$ai_trace_id", "mat_$ai_session_id", "mat_$ai_is_error", "mat_$ai_prompt_name", "mat_$ai_experiment_id"]
    }
    # Product fixtures insert into the historical logs32 table.
    logs_distributed = {
      engine = "Distributed('posthog_single_shard', '${var.database}', 'logs32')"
    }
  }
}

module "catalog" {
  source = "../catalog"

  database            = var.database
  ttl                 = !var.test
  test                = var.test
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password

  objects = setsubtract(
    setunion(local.objects, var.kafka ? local.kafka_objects : [], var.test ? local.test_objects : []),
    var.test ? local.not_in_tests : [],
  )

  overrides = merge({
    kafka_billing_usage_records = {
      engine   = "Kafka(warpstream_ingestion)"
      settings = "date_time_input_format = 'best_effort', kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_billing_usage_records', kafka_topic_list = 'clickhouse_billing_usage_records'"
    }
  }, { for name, override in local.test_overrides : name => override if var.test })

  deployment = {
    sharded = merge(local.deployment_defaults, { cluster = "aux" })
    global  = merge(local.deployment_defaults, { cluster = "posthog" })
    families = { for name in [
      "adhoc_events_deletion",
      "ai_events",
      "app_metrics",
      "billing_usage_records",
      "channel_definition",
      "clickhouse_cleanup",
      "cohort_membership",
      "cohortpeople",
      "distinct_id_usage",
      "dmat_slot_assignments",
      "document_embeddings",
      "duplicate_events",
      "error_tracking",
      "events",
      "events_dead_letter_queue",
      "events_json",
      "events_recent",
      "events_team_daily_stats",
      "exchange_rate",
      "experiments_preaggregated",
      "flag_evaluations",
      "groups",
      "heatmaps",
      "hog_invocation_results",
      "ingestion_warnings",
      "llma_metrics_daily",
      "log_entries",
      "logs",
      "marketing_preaggregated",
      "message_assets",
      "metrics",
      "performance_events",
      "person",
      "person_distinct_id",
      "person_distinct_id_overrides",
      "person_overrides",
      "person_static_cohort",
      "pg_embeddings",
      "platform_alert_events",
      "plugin_log_entries",
      "preaggregation_results",
      "precalculated",
      "property_values",
      "query_log_archive",
      "raw_sessions",
      "session_replay",
      "sessions",
      "system_processes",
      "tophog",
      "traces",
      "usage_report_events_preagg",
      "warehouse_object_reads_daily",
      "web_bot_definition",
      "web_preaggregated",
    ] : name => local.deployment_defaults }
  }
}
