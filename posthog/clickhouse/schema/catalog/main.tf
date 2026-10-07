variable "node" {
  description = "The server these objects live on: { name, host, port, leader }. Null puts them on the provider's host."
  type        = any
  default     = null
}

variable "database" {
  type    = string
  default = "posthog"
}

variable "objects" {
  description = "Names of the objects to create on this node."
  type        = set(string)
}

variable "overrides" {
  description = "Changes to single objects, by object name. The keys are listed in lib/table/main.tf."
  type        = any
  default     = {}
}

variable "test" {
  description = "Use the definitions the test suite expects."
  type        = bool
  default     = false
}

variable "deployment" {
  description = "Operational settings: defaults for each layout, plus per-family differences such as Keeper paths and Kafka topic namespaces."
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
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.adhoc_events_deletion, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "ai_events" {
  source     = "./ai_events"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.ai_events, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "app_metrics" {
  source     = "./app_metrics"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.app_metrics, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "channel_definition" {
  source              = "./channel_definition"
  node                = var.node
  database            = var.database
  deployment          = merge(try(var.deployment.families.channel_definition, {}), { overrides = var.overrides })
  objects             = var.objects
  test                = var.test
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}

module "clickhouse_cleanup" {
  source     = "./clickhouse_cleanup"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.clickhouse_cleanup, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "cohort_membership" {
  source     = "./cohort_membership"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.cohort_membership, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "cohortpeople" {
  source     = "./cohortpeople"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.cohortpeople, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "custom_metrics" {
  source     = "./custom_metrics"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.custom_metrics, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "distinct_id_usage" {
  source     = "./distinct_id_usage"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.distinct_id_usage, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "dmat_slot_assignments" {
  source              = "./dmat_slot_assignments"
  node                = var.node
  database            = var.database
  deployment          = merge(try(var.deployment.families.dmat_slot_assignments, {}), { overrides = var.overrides })
  objects             = var.objects
  test                = var.test
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}

module "document_embeddings" {
  source     = "./document_embeddings"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.document_embeddings, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "duplicate_events" {
  source     = "./duplicate_events"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.duplicate_events, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "error_tracking" {
  source     = "./error_tracking"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.error_tracking, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "events" {
  source     = "./events"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.events, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "events_dead_letter_queue" {
  source     = "./events_dead_letter_queue"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.events_dead_letter_queue, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "events_json" {
  source     = "./events_json"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.events_json, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "events_recent" {
  source     = "./events_recent"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.events_recent, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
  depends_on = [module.events]
}

module "events_team_daily_stats" {
  source     = "./events_team_daily_stats"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.events_team_daily_stats, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "exchange_rate" {
  source              = "./exchange_rate"
  node                = var.node
  database            = var.database
  deployment          = merge(try(var.deployment.families.exchange_rate, {}), { overrides = var.overrides })
  objects             = var.objects
  test                = var.test
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}

module "experiments_preaggregated" {
  source     = "./experiments_preaggregated"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.experiments_preaggregated, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "flag_evaluations" {
  source     = "./flag_evaluations"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.flag_evaluations, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "groups" {
  source     = "./groups"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.groups, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "heatmaps" {
  source     = "./heatmaps"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.heatmaps, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "hog_invocation_results" {
  source     = "./hog_invocation_results"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.hog_invocation_results, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "ingestion_warnings" {
  source     = "./ingestion_warnings"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.ingestion_warnings, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "llma_metrics_daily" {
  source     = "./llma_metrics_daily"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.llma_metrics_daily, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "log_entries" {
  source     = "./log_entries"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.log_entries, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "logs" {
  source     = "./logs"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.logs, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "marketing_preaggregated" {
  source     = "./marketing_preaggregated"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.marketing_preaggregated, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "message_assets" {
  source     = "./message_assets"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.message_assets, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "metrics" {
  source     = "./metrics"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.metrics, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "performance_events" {
  source     = "./performance_events"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.performance_events, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "person" {
  source     = "./person"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.person, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  depends_on = [module.person_distinct_id]
}

module "person_distinct_id" {
  source     = "./person_distinct_id"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.person_distinct_id, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "person_distinct_id_overrides" {
  source              = "./person_distinct_id_overrides"
  node                = var.node
  database            = var.database
  deployment          = merge(try(var.deployment.families.person_distinct_id_overrides, {}), { overrides = var.overrides })
  objects             = var.objects
  test                = var.test
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}

module "person_overrides" {
  source              = "./person_overrides"
  node                = var.node
  database            = var.database
  deployment          = merge(try(var.deployment.families.person_overrides, {}), { overrides = var.overrides })
  objects             = var.objects
  test                = var.test
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}

module "person_static_cohort" {
  source     = "./person_static_cohort"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.person_static_cohort, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "pg_embeddings" {
  source     = "./pg_embeddings"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.pg_embeddings, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "platform_alert_events" {
  source     = "./platform_alert_events"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.platform_alert_events, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "plugin_log_entries" {
  source     = "./plugin_log_entries"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.plugin_log_entries, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "preaggregation_results" {
  source     = "./preaggregation_results"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.preaggregation_results, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "precalculated" {
  source     = "./precalculated"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.precalculated, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "property_values" {
  source     = "./property_values"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.property_values, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "query_log_archive" {
  source     = "./query_log_archive"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.query_log_archive, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "raw_sessions" {
  source     = "./raw_sessions"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.raw_sessions, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  depends_on = [module.events, module.session_replay]
}

module "session_replay" {
  source     = "./session_replay"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.session_replay, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "sessions" {
  source     = "./sessions"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.sessions, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  depends_on = [module.events]
}

module "system_processes" {
  source     = "./system_processes"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.system_processes, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "tophog" {
  source     = "./tophog"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.tophog, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "traces" {
  source     = "./traces"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.traces, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "usage_report_events_preagg" {
  source     = "./usage_report_events_preagg"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.usage_report_events_preagg, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "warehouse_object_reads_daily" {
  source     = "./warehouse_object_reads_daily"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.warehouse_object_reads_daily, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
  ttl        = var.ttl
}

module "web_bot_definition" {
  source              = "./web_bot_definition"
  node                = var.node
  database            = var.database
  deployment          = merge(try(var.deployment.families.web_bot_definition, {}), { overrides = var.overrides })
  objects             = var.objects
  test                = var.test
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}

module "web_preaggregated" {
  source              = "./web_preaggregated"
  node                = var.node
  database            = var.database
  deployment          = merge(try(var.deployment.families.web_preaggregated, {}), { overrides = var.overrides })
  objects             = var.objects
  test                = var.test
  ttl                 = var.ttl
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}

# Production objects from before this catalogue. Only Cloud roots list their objects.

module "ai_events_merge" {
  source     = "./ai_events_merge"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.ai_events_merge, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "async_deletion" {
  source     = "./async_deletion"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.async_deletion, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "custom_metrics_cloud" {
  source     = "./custom_metrics_cloud"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.custom_metrics_cloud, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "events_json_buffer" {
  source     = "./events_json_buffer"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.events_json_buffer, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "log_entries_cloud" {
  source     = "./log_entries_cloud"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.log_entries_cloud, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "ops_metrics" {
  source     = "./ops_metrics"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.ops_metrics, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "ops_stats" {
  source     = "./ops_stats"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.ops_stats, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "person_collapsing" {
  source     = "./person_collapsing"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.person_collapsing, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "query_log_archive_v3" {
  source     = "./query_log_archive_v3"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.query_log_archive_v3, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "session_recording_events" {
  source     = "./session_recording_events"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.session_recording_events, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "sessions_new" {
  source     = "./sessions_new"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.sessions_new, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "web_bot_definition_cloud" {
  source     = "./web_bot_definition_cloud"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.web_bot_definition_cloud, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}

module "web_preaggregated_cloud" {
  source     = "./web_preaggregated_cloud"
  node       = var.node
  database   = var.database
  deployment = merge(try(var.deployment.families.web_preaggregated_cloud, {}), { overrides = var.overrides })
  objects    = var.objects
  test       = var.test
}
