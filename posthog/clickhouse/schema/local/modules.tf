module "catalog" {
  source = "../catalog"

  database            = var.database
  ttl                 = !var.test
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
  deployment = {
    sharded = { components = setsubtract(local.components, ["test"]), cluster = "aux" }
    global  = { components = setsubtract(local.components, ["read", "test"]), cluster = "posthog" }
    families = {
      adhoc_events_deletion = { components = local.components }
      ai_events             = { components = local.components }
      app_metrics           = { components = local.components }
      channel_definition    = { components = local.components }
      clickhouse_cleanup    = { components = local.components }
      cohort_membership     = { components = local.components }
      cohortpeople          = { components = local.components }
      custom_metrics        = { components = local.components }
      distinct_id_usage     = { components = local.components }
      dmat_slot_assignments = { components = local.components }
      document_embeddings   = { components = local.components }
      duplicate_events      = { components = local.components }
      error_tracking        = { components = local.components }
      events = {
        components = local.components
        overrides = var.test ? {
          # Runtime materialization starts from the same empty state as the existing test schema.
          sharded_events = {
            drop_columns = ["mat_$ai_trace_id", "mat_$ai_session_id", "mat_$ai_is_error", "mat_$ai_prompt_name", "mat_$ai_experiment_id"]
            drop_indexes = ["bloom_filter_$ai_trace_id", "bloom_filter_$ai_session_id", "minmax_$ai_session_id", "set_$ai_is_error", "bloom_filter_$ai_prompt_name", "minmax_$ai_prompt_name", "bloom_filter_$ai_experiment_id", "minmax_$ai_experiment_id"]
          }
          events = {
            drop_columns = ["mat_$ai_trace_id", "mat_$ai_session_id", "mat_$ai_is_error", "mat_$ai_prompt_name", "mat_$ai_experiment_id"]
          }
        } : {}
      }
      events_dead_letter_queue  = { components = local.components }
      events_json               = { components = local.components }
      events_recent             = { components = local.components }
      events_team_daily_stats   = { components = local.components }
      exchange_rate             = { components = local.components }
      experiments_preaggregated = { components = local.components }
      flag_evaluations          = { components = local.components }
      groups                    = { components = local.components }
      heatmaps                  = { components = local.components }
      hog_invocation_results    = { components = local.components }
      ingestion_warnings        = { components = local.components }
      llma_metrics_daily        = { components = local.components }
      log_entries               = { components = local.components }
      logs = {
        components = local.components
        overrides = {
          # Both local entry points must read the same storage that inserts through logs reach.
          logs_distributed = {
            engine = "Distributed('posthog_single_shard', '${var.database}', 'logs32')"
          }
        }
      }
      marketing_preaggregated      = { components = local.components }
      message_assets               = { components = local.components }
      metrics                      = { components = local.components }
      performance_events           = { components = local.components }
      person                       = { components = local.components }
      person_distinct_id           = { components = local.components }
      person_distinct_id_overrides = { components = local.components }
      person_overrides             = { components = local.components }
      person_static_cohort         = { components = local.components }
      pg_embeddings                = { components = local.components }
      platform_alert_events        = { components = local.components }
      plugin_log_entries           = { components = local.components }
      preaggregation_results       = { components = local.components }
      precalculated                = { components = local.components }
      property_values              = { components = local.components }
      query_log_archive            = { components = local.components }
      raw_sessions                 = { components = local.components }
      session_replay               = { components = local.components }
      sessions                     = { components = local.components }
      system_processes             = { components = local.components }
      tophog                       = { components = local.components }
      traces = {
        components = local.components
        # Product fixtures rebuild their own span and attribute tables without ingestion views.
        exclude = var.test ? [
          "trace_span_to_attributes", "trace_span_to_attributes2",
          "trace_span_to_resource_attributes", "trace_span_to_resource_attributes2",
          "trace_span_to_span_attributes", "trace_span_to_span_attributes2",
          "trace_spans_to_kafka_metrics_mv",
        ] : []
      }
      usage_report_events_preagg = { components = local.components }
      web_bot_definition         = { components = local.components }
      web_preaggregated          = { components = local.components }
      billing_usage_records = {
        overrides = {
          kafka_billing_usage_records = {
            engine   = "Kafka(warpstream_ingestion)"
            settings = "date_time_input_format = 'best_effort', kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_billing_usage_records', kafka_topic_list = 'clickhouse_billing_usage_records'"
          }
        }
      }
    }
  }
}
