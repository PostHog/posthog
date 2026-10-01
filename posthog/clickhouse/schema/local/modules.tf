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
      adhoc_events_deletion        = { components = local.components }
      ai_events                    = { components = local.components }
      app_metrics                  = { components = local.components }
      channel_definition           = { components = local.components }
      clickhouse_cleanup           = { components = local.components }
      cohort_membership            = { components = local.components }
      cohortpeople                 = { components = local.components }
      custom_metrics               = { components = local.components }
      distinct_id_usage            = { components = local.components }
      dmat_slot_assignments        = { components = local.components }
      document_embeddings          = { components = local.components }
      duplicate_events             = { components = local.components }
      error_tracking               = { components = local.components }
      events                       = { components = local.components }
      events_dead_letter_queue     = { components = local.components }
      events_json                  = { components = local.components }
      events_recent                = { components = local.components }
      events_team_daily_stats      = { components = local.components }
      exchange_rate                = { components = local.components }
      experiments_preaggregated    = { components = local.components }
      flag_evaluations             = { components = local.components }
      groups                       = { components = local.components }
      heatmaps                     = { components = local.components }
      hog_invocation_results       = { components = local.components }
      ingestion_warnings           = { components = local.components }
      llma_metrics_daily           = { components = local.components }
      log_entries                  = { components = local.components }
      logs                         = { components = local.components }
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
      traces                       = { components = local.components }
      usage_report_events_preagg   = { components = local.components }
      web_bot_definition           = { components = local.components }
      web_preaggregated            = { components = local.components }
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

moved {
  from = module.billing_usage_records.module.sharded_billing_usage_records
  to   = module.catalog.module.billing_usage_records.module.storage
}
moved {
  from = module.billing_usage_records.module.billing_usage_records
  to   = module.catalog.module.billing_usage_records.module.read
}
moved {
  from = module.billing_usage_records.module.writable_billing_usage_records
  to   = module.catalog.module.billing_usage_records.module.write
}
moved {
  from = module.billing_usage_records.module.kafka_billing_usage_records
  to   = module.catalog.module.billing_usage_records.module.kafka
}
moved {
  from = module.billing_usage_records.module.billing_usage_records_mv
  to   = module.catalog.module.billing_usage_records.module.mv
}
moved {
  from = module.property_definitions.module.property_definitions
  to   = module.catalog.module.property_definitions.module.storage
}

moved {
  from = module.adhoc_events_deletion
  to   = module.catalog.module.adhoc_events_deletion
}

moved {
  from = module.ai_events
  to   = module.catalog.module.ai_events
}

moved {
  from = module.app_metrics
  to   = module.catalog.module.app_metrics
}

moved {
  from = module.channel_definition
  to   = module.catalog.module.channel_definition
}

moved {
  from = module.clickhouse_cleanup
  to   = module.catalog.module.clickhouse_cleanup
}

moved {
  from = module.cohort_membership
  to   = module.catalog.module.cohort_membership
}

moved {
  from = module.cohortpeople
  to   = module.catalog.module.cohortpeople
}

moved {
  from = module.custom_metrics
  to   = module.catalog.module.custom_metrics
}

moved {
  from = module.distinct_id_usage
  to   = module.catalog.module.distinct_id_usage
}

moved {
  from = module.dmat_slot_assignments
  to   = module.catalog.module.dmat_slot_assignments
}

moved {
  from = module.document_embeddings
  to   = module.catalog.module.document_embeddings
}

moved {
  from = module.duplicate_events
  to   = module.catalog.module.duplicate_events
}

moved {
  from = module.error_tracking
  to   = module.catalog.module.error_tracking
}

moved {
  from = module.events
  to   = module.catalog.module.events
}

moved {
  from = module.events_dead_letter_queue
  to   = module.catalog.module.events_dead_letter_queue
}

moved {
  from = module.events_json
  to   = module.catalog.module.events_json
}

moved {
  from = module.events_recent
  to   = module.catalog.module.events_recent
}

moved {
  from = module.events_team_daily_stats
  to   = module.catalog.module.events_team_daily_stats
}

moved {
  from = module.exchange_rate
  to   = module.catalog.module.exchange_rate
}

moved {
  from = module.experiments_preaggregated
  to   = module.catalog.module.experiments_preaggregated
}

moved {
  from = module.flag_evaluations
  to   = module.catalog.module.flag_evaluations
}

moved {
  from = module.groups
  to   = module.catalog.module.groups
}

moved {
  from = module.heatmaps
  to   = module.catalog.module.heatmaps
}

moved {
  from = module.hog_invocation_results
  to   = module.catalog.module.hog_invocation_results
}

moved {
  from = module.ingestion_warnings
  to   = module.catalog.module.ingestion_warnings
}

moved {
  from = module.llma_metrics_daily
  to   = module.catalog.module.llma_metrics_daily
}

moved {
  from = module.log_entries
  to   = module.catalog.module.log_entries
}

moved {
  from = module.logs
  to   = module.catalog.module.logs
}

moved {
  from = module.marketing_preaggregated
  to   = module.catalog.module.marketing_preaggregated
}

moved {
  from = module.message_assets
  to   = module.catalog.module.message_assets
}

moved {
  from = module.metrics
  to   = module.catalog.module.metrics
}

moved {
  from = module.performance_events
  to   = module.catalog.module.performance_events
}

moved {
  from = module.person
  to   = module.catalog.module.person
}

moved {
  from = module.person_distinct_id
  to   = module.catalog.module.person_distinct_id
}

moved {
  from = module.person_distinct_id_overrides
  to   = module.catalog.module.person_distinct_id_overrides
}

moved {
  from = module.person_overrides
  to   = module.catalog.module.person_overrides
}

moved {
  from = module.person_static_cohort
  to   = module.catalog.module.person_static_cohort
}

moved {
  from = module.pg_embeddings
  to   = module.catalog.module.pg_embeddings
}

moved {
  from = module.platform_alert_events
  to   = module.catalog.module.platform_alert_events
}

moved {
  from = module.plugin_log_entries
  to   = module.catalog.module.plugin_log_entries
}

moved {
  from = module.preaggregation_results
  to   = module.catalog.module.preaggregation_results
}

moved {
  from = module.precalculated
  to   = module.catalog.module.precalculated
}

moved {
  from = module.property_values
  to   = module.catalog.module.property_values
}

moved {
  from = module.query_log_archive
  to   = module.catalog.module.query_log_archive
}

moved {
  from = module.raw_sessions
  to   = module.catalog.module.raw_sessions
}

moved {
  from = module.session_replay
  to   = module.catalog.module.session_replay
}

moved {
  from = module.sessions
  to   = module.catalog.module.sessions
}

moved {
  from = module.system_processes
  to   = module.catalog.module.system_processes
}

moved {
  from = module.tophog
  to   = module.catalog.module.tophog
}

moved {
  from = module.traces
  to   = module.catalog.module.traces
}

moved {
  from = module.usage_report_events_preagg
  to   = module.catalog.module.usage_report_events_preagg
}

moved {
  from = module.web_bot_definition
  to   = module.catalog.module.web_bot_definition
}

moved {
  from = module.web_preaggregated
  to   = module.catalog.module.web_preaggregated
}
