variable "database" {
  type    = string
  default = "posthog"
}

variable "deployment" {
  description = "Default placement for each layout, plus explicit per-family differences. Each family's deployment is validated by table_family."
  type = object({
    sharded  = any
    global   = any
    families = optional(any, {})
  })
}

variable "ttl" {
  type    = bool
  default = true
}
variable "dictionary_user" {
  type    = string
  default = "default"
}
variable "dictionary_password" {
  type      = string
  default   = ""
  sensitive = true
}

module "adhoc_events_deletion" {
  source     = "./adhoc_events_deletion"
  database   = var.database
  deployment = try(var.deployment.families.adhoc_events_deletion, { components = [] })
  ttl        = var.ttl
}

module "ai_events" {
  source     = "./ai_events"
  database   = var.database
  deployment = try(var.deployment.families.ai_events, { components = [] })
  ttl        = var.ttl
}

module "app_metrics" {
  source     = "./app_metrics"
  database   = var.database
  deployment = try(var.deployment.families.app_metrics, { components = [] })
  ttl        = var.ttl
}

module "channel_definition" {
  source              = "./channel_definition"
  database            = var.database
  deployment          = try(var.deployment.families.channel_definition, { components = [] })
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}

module "clickhouse_cleanup" {
  source     = "./clickhouse_cleanup"
  database   = var.database
  deployment = try(var.deployment.families.clickhouse_cleanup, { components = [] })
  ttl        = var.ttl
}

module "cohort_membership" {
  source     = "./cohort_membership"
  database   = var.database
  deployment = try(var.deployment.families.cohort_membership, { components = [] })
}

module "cohortpeople" {
  source     = "./cohortpeople"
  database   = var.database
  deployment = try(var.deployment.families.cohortpeople, { components = [] })
}

module "custom_metrics" {
  source     = "./custom_metrics"
  database   = var.database
  deployment = try(var.deployment.families.custom_metrics, { components = [] })
}

module "distinct_id_usage" {
  source     = "./distinct_id_usage"
  database   = var.database
  deployment = try(var.deployment.families.distinct_id_usage, { components = [] })
  ttl        = var.ttl
}

module "dmat_slot_assignments" {
  source              = "./dmat_slot_assignments"
  database            = var.database
  deployment          = try(var.deployment.families.dmat_slot_assignments, { components = [] })
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}

module "document_embeddings" {
  source     = "./document_embeddings"
  database   = var.database
  deployment = try(var.deployment.families.document_embeddings, { components = [] })
  ttl        = var.ttl
}

module "duplicate_events" {
  source     = "./duplicate_events"
  database   = var.database
  deployment = try(var.deployment.families.duplicate_events, { components = [] })
  ttl        = var.ttl
}

module "error_tracking" {
  source     = "./error_tracking"
  database   = var.database
  deployment = try(var.deployment.families.error_tracking, { components = [] })
}

module "events" {
  source     = "./events"
  database   = var.database
  deployment = try(var.deployment.families.events, { components = [] })
}

module "events_dead_letter_queue" {
  source     = "./events_dead_letter_queue"
  database   = var.database
  deployment = try(var.deployment.families.events_dead_letter_queue, { components = [] })
  ttl        = var.ttl
}

module "events_json" {
  source     = "./events_json"
  database   = var.database
  deployment = try(var.deployment.families.events_json, { components = [] })
}

module "events_recent" {
  source     = "./events_recent"
  database   = var.database
  deployment = try(var.deployment.families.events_recent, { components = [] })
  ttl        = var.ttl
  depends_on = [module.events]
}

module "events_team_daily_stats" {
  source     = "./events_team_daily_stats"
  database   = var.database
  deployment = try(var.deployment.families.events_team_daily_stats, { components = [] })
}

module "exchange_rate" {
  source              = "./exchange_rate"
  database            = var.database
  deployment          = try(var.deployment.families.exchange_rate, { components = [] })
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}

module "experiments_preaggregated" {
  source     = "./experiments_preaggregated"
  database   = var.database
  deployment = try(var.deployment.families.experiments_preaggregated, { components = [] })
  ttl        = var.ttl
}

module "flag_evaluations" {
  source     = "./flag_evaluations"
  database   = var.database
  deployment = try(var.deployment.families.flag_evaluations, { components = [] })
  ttl        = var.ttl
}

module "groups" {
  source     = "./groups"
  database   = var.database
  deployment = try(var.deployment.families.groups, { components = [] })
}

module "heatmaps" {
  source     = "./heatmaps"
  database   = var.database
  deployment = try(var.deployment.families.heatmaps, { components = [] })
  ttl        = var.ttl
}

module "hog_invocation_results" {
  source     = "./hog_invocation_results"
  database   = var.database
  deployment = try(var.deployment.families.hog_invocation_results, { components = [] })
  ttl        = var.ttl
}

module "ingestion_warnings" {
  source     = "./ingestion_warnings"
  database   = var.database
  deployment = try(var.deployment.families.ingestion_warnings, { components = [] })
  ttl        = var.ttl
}

module "llma_metrics_daily" {
  source     = "./llma_metrics_daily"
  database   = var.database
  deployment = try(var.deployment.families.llma_metrics_daily, { components = [] })
}

module "log_entries" {
  source     = "./log_entries"
  database   = var.database
  deployment = try(var.deployment.families.log_entries, { components = [] })
  ttl        = var.ttl
}

module "logs" {
  source     = "./logs"
  database   = var.database
  deployment = try(var.deployment.families.logs, { components = [] })
  ttl        = var.ttl
}

module "marketing_preaggregated" {
  source     = "./marketing_preaggregated"
  database   = var.database
  deployment = try(var.deployment.families.marketing_preaggregated, { components = [] })
  ttl        = var.ttl
}

module "message_assets" {
  source     = "./message_assets"
  database   = var.database
  deployment = try(var.deployment.families.message_assets, { components = [] })
  ttl        = var.ttl
}

module "metrics" {
  source     = "./metrics"
  database   = var.database
  deployment = try(var.deployment.families.metrics, { components = [] })
  ttl        = var.ttl
}

module "performance_events" {
  source     = "./performance_events"
  database   = var.database
  deployment = try(var.deployment.families.performance_events, { components = [] })
  ttl        = var.ttl
}

module "person" {
  source     = "./person"
  database   = var.database
  deployment = try(var.deployment.families.person, { components = [] })
  depends_on = [module.person_distinct_id]
}

module "person_distinct_id" {
  source     = "./person_distinct_id"
  database   = var.database
  deployment = try(var.deployment.families.person_distinct_id, { components = [] })
}

module "person_distinct_id_overrides" {
  source              = "./person_distinct_id_overrides"
  database            = var.database
  deployment          = try(var.deployment.families.person_distinct_id_overrides, { components = [] })
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}

module "person_overrides" {
  source              = "./person_overrides"
  database            = var.database
  deployment          = try(var.deployment.families.person_overrides, { components = [] })
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}

module "person_static_cohort" {
  source     = "./person_static_cohort"
  database   = var.database
  deployment = try(var.deployment.families.person_static_cohort, { components = [] })
}

module "pg_embeddings" {
  source     = "./pg_embeddings"
  database   = var.database
  deployment = try(var.deployment.families.pg_embeddings, { components = [] })
}

module "platform_alert_events" {
  source     = "./platform_alert_events"
  database   = var.database
  deployment = try(var.deployment.families.platform_alert_events, { components = [] })
  ttl        = var.ttl
}

module "plugin_log_entries" {
  source     = "./plugin_log_entries"
  database   = var.database
  deployment = try(var.deployment.families.plugin_log_entries, { components = [] })
  ttl        = var.ttl
}

module "preaggregation_results" {
  source     = "./preaggregation_results"
  database   = var.database
  deployment = try(var.deployment.families.preaggregation_results, { components = [] })
  ttl        = var.ttl
}

module "precalculated" {
  source     = "./precalculated"
  database   = var.database
  deployment = try(var.deployment.families.precalculated, { components = [] })
}

module "property_values" {
  source     = "./property_values"
  database   = var.database
  deployment = try(var.deployment.families.property_values, { components = [] })
  ttl        = var.ttl
}

module "query_log_archive" {
  source     = "./query_log_archive"
  database   = var.database
  deployment = try(var.deployment.families.query_log_archive, { components = [] })
}

module "raw_sessions" {
  source     = "./raw_sessions"
  database   = var.database
  deployment = try(var.deployment.families.raw_sessions, { components = [] })
  depends_on = [module.events, module.session_replay]
}

module "session_replay" {
  source     = "./session_replay"
  database   = var.database
  deployment = try(var.deployment.families.session_replay, { components = [] })
  ttl        = var.ttl
}

module "sessions" {
  source     = "./sessions"
  database   = var.database
  deployment = try(var.deployment.families.sessions, { components = [] })
  depends_on = [module.events]
}

module "system_processes" {
  source     = "./system_processes"
  database   = var.database
  deployment = try(var.deployment.families.system_processes, { components = [] })
}

module "tophog" {
  source     = "./tophog"
  database   = var.database
  deployment = try(var.deployment.families.tophog, { components = [] })
  ttl        = var.ttl
}

module "traces" {
  source     = "./traces"
  database   = var.database
  deployment = try(var.deployment.families.traces, { components = [] })
  ttl        = var.ttl
}

module "usage_report_events_preagg" {
  source     = "./usage_report_events_preagg"
  database   = var.database
  deployment = try(var.deployment.families.usage_report_events_preagg, { components = [] })
  ttl        = var.ttl
}

module "web_bot_definition" {
  source              = "./web_bot_definition"
  database            = var.database
  deployment          = try(var.deployment.families.web_bot_definition, { components = [] })
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}

module "web_preaggregated" {
  source              = "./web_preaggregated"
  database            = var.database
  deployment          = try(var.deployment.families.web_preaggregated, { components = [] })
  ttl                 = var.ttl
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}
