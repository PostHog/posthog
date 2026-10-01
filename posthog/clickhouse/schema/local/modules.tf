module "adhoc_events_deletion" {
  source = "../modules/adhoc_events_deletion"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "ai_events" {
  source = "../modules/ai_events"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "app_metrics" {
  source = "../modules/app_metrics"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "channel_definition" {
  source = "../modules/channel_definition"

  database            = var.database
  zk_path_suffix      = var.zk_path_suffix
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
  components          = local.components
}

module "clickhouse_cleanup" {
  source = "../modules/clickhouse_cleanup"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "cohort_membership" {
  source = "../modules/cohort_membership"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components
}

module "cohortpeople" {
  source = "../modules/cohortpeople"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components
}

module "custom_metrics" {
  source = "../modules/custom_metrics"

  database   = var.database
  components = local.components
}

module "distinct_id_usage" {
  source = "../modules/distinct_id_usage"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "dmat_slot_assignments" {
  source = "../modules/dmat_slot_assignments"

  database            = var.database
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
  components          = local.components
}

module "document_embeddings" {
  source = "../modules/document_embeddings"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "duplicate_events" {
  source = "../modules/duplicate_events"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "error_tracking" {
  source = "../modules/error_tracking"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components
}

module "events" {
  source = "../modules/events"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components
}

module "events_dead_letter_queue" {
  source = "../modules/events_dead_letter_queue"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "events_json" {
  source = "../modules/events_json"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components
}

module "events_recent" {
  source = "../modules/events_recent"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components

  depends_on = [module.events]
}

module "events_team_daily_stats" {
  source = "../modules/events_team_daily_stats"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components
}

module "exchange_rate" {
  source = "../modules/exchange_rate"

  database            = var.database
  zk_path_suffix      = var.zk_path_suffix
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
  components          = local.components
}

module "experiments_preaggregated" {
  source = "../modules/experiments_preaggregated"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "flag_evaluations" {
  source = "../modules/flag_evaluations"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "groups" {
  source = "../modules/groups"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components
}

module "heatmaps" {
  source = "../modules/heatmaps"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "hog_invocation_results" {
  source = "../modules/hog_invocation_results"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "ingestion_warnings" {
  source = "../modules/ingestion_warnings"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "llma_metrics_daily" {
  source = "../modules/llma_metrics_daily"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components
}

module "log_entries" {
  source = "../modules/log_entries"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "logs" {
  source = "../modules/logs"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "marketing_preaggregated" {
  source = "../modules/marketing_preaggregated"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "message_assets" {
  source = "../modules/message_assets"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "metrics" {
  source = "../modules/metrics"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "performance_events" {
  source = "../modules/performance_events"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "person" {
  source = "../modules/person"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components

  depends_on = [module.person_distinct_id]
}

module "person_distinct_id" {
  source = "../modules/person_distinct_id"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components
}

module "person_distinct_id_overrides" {
  source = "../modules/person_distinct_id_overrides"

  database            = var.database
  zk_path_suffix      = var.zk_path_suffix
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
  components          = local.components
}

module "person_overrides" {
  source = "../modules/person_overrides"

  database            = var.database
  zk_path_suffix      = var.zk_path_suffix
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
  components          = local.components
}

module "person_static_cohort" {
  source = "../modules/person_static_cohort"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components
}

module "pg_embeddings" {
  source = "../modules/pg_embeddings"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components
}

module "platform_alert_events" {
  source = "../modules/platform_alert_events"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "plugin_log_entries" {
  source = "../modules/plugin_log_entries"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "preaggregation_results" {
  source = "../modules/preaggregation_results"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "precalculated" {
  source = "../modules/precalculated"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components
}

module "property_values" {
  source = "../modules/property_values"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "query_log_archive" {
  source = "../modules/query_log_archive"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components
}

module "raw_sessions" {
  source = "../modules/raw_sessions"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components

  depends_on = [module.events, module.session_replay]
}

module "session_replay" {
  source = "../modules/session_replay"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "sessions" {
  source = "../modules/sessions"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  components     = local.components

  depends_on = [module.events]
}

module "system_processes" {
  source = "../modules/system_processes"

  database   = var.database
  components = local.components
}

module "tophog" {
  source = "../modules/tophog"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "traces" {
  source = "../modules/traces"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "usage_report_events_preagg" {
  source = "../modules/usage_report_events_preagg"

  database       = var.database
  zk_path_suffix = var.zk_path_suffix
  ttl            = !var.test
  components     = local.components
}

module "web_bot_definition" {
  source = "../modules/web_bot_definition"

  database            = var.database
  zk_path_suffix      = var.zk_path_suffix
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
  components          = local.components
}

module "web_preaggregated" {
  source = "../modules/web_preaggregated"

  database            = var.database
  zk_path_suffix      = var.zk_path_suffix
  ttl                 = !var.test
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
  components          = local.components
}

module "catalog" {
  source = "../catalog"

  database = var.database
  deployment = {
    sharded = { components = setsubtract(local.components, ["test"]), cluster = "aux" }
    global  = { components = setsubtract(local.components, ["read", "test"]), cluster = "posthog" }
    families = {
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
