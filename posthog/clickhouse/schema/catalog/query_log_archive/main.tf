variable "node" {
  description = "The server these objects live on: { name, host, port, leader }. Null puts them on the provider's host."
  type        = any
  default     = null
}

variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
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

locals {
}

# Column lists that more than one object uses.

locals {
  query_log_archive_buffer_columns = [
    { name = "hostname", type = "LowCardinality(String)" },
    { name = "user", type = "LowCardinality(String)" },
    { name = "query_id", type = "String" },
    { name = "initial_query_id", type = "String" },
    { name = "is_initial_query", type = "UInt8" },
    { name = "type", type = "Enum8('QueryStart' = 1, 'QueryFinish' = 2, 'ExceptionBeforeStart' = 3, 'ExceptionWhileProcessing' = 4)" },
    { name = "event_date", type = "Date" },
    { name = "event_time", type = "DateTime" },
    { name = "event_time_microseconds", type = "DateTime64(6)" },
    { name = "query_start_time", type = "DateTime" },
    { name = "query_start_time_microseconds", type = "DateTime64(6)" },
    { name = "query_duration_ms", type = "UInt64" },
    { name = "read_rows", type = "UInt64" },
    { name = "read_bytes", type = "UInt64" },
    { name = "written_rows", type = "UInt64" },
    { name = "written_bytes", type = "UInt64" },
    { name = "result_rows", type = "UInt64" },
    { name = "result_bytes", type = "UInt64" },
    { name = "memory_usage", type = "UInt64" },
    { name = "peak_threads_usage", type = "UInt64" },
    { name = "current_database", type = "LowCardinality(String)" },
    { name = "query", type = "String" },
    { name = "formatted_query", type = "String" },
    { name = "normalized_query_hash", type = "UInt64" },
    { name = "query_kind", type = "LowCardinality(String)" },
    { name = "exception_code", type = "Int32" },
    { name = "exception", type = "String" },
    { name = "stack_trace", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "log_comment", type = "JSON(max_dynamic_paths = 256, access_method LowCardinality(String), alert_config_id String, api_key_label String, api_key_mask String, batch_export_id String, chargeable Bool, client_query_id String, cohort_id Int64, `dagster.job_name` String, `dagster.run_id` String, `dagster.tags.owner` String, dashboard_id Int64, experiment_feature_flag_key String, experiment_id Int64, feature LowCardinality(String), id String, insight_id Int64, is_impersonated Bool, kind LowCardinality(String), name String, org_id String, person_on_events_mode LowCardinality(String), product LowCardinality(String), query_type LowCardinality(String), request_name String, route_id String, service_name String, session_id String, table_id String, team_id Int64, `temporal.activity_id` String, `temporal.activity_type` String, `temporal.attempt` Int64, `temporal.workflow_id` String, `temporal.workflow_namespace` String, `temporal.workflow_run_id` String, `temporal.workflow_type` String, user_id Int64, warehouse_query Bool, workflow LowCardinality(String), workload LowCardinality(String), SKIP cache_key, SKIP filter, SKIP hogql_features, SKIP http_referer, SKIP http_request_id, SKIP http_user_agent, SKIP query_settings, SKIP timings, SKIP user_email)" },
    { name = "ProfileEvents", type = "Map(String, UInt64)" },
  ]

  query_log_archive_v2_columns = [
    { name = "hostname", type = "LowCardinality(String)" },
    { name = "user", type = "LowCardinality(String)" },
    { name = "query_id", type = "String" },
    { name = "initial_query_id", type = "String" },
    { name = "is_initial_query", type = "UInt8" },
    { name = "type", type = "Enum8('QueryStart' = 1, 'QueryFinish' = 2, 'ExceptionBeforeStart' = 3, 'ExceptionWhileProcessing' = 4)" },
    { name = "event_date", type = "Date" },
    { name = "event_time", type = "DateTime" },
    { name = "event_time_microseconds", type = "DateTime64(6)" },
    { name = "query_start_time", type = "DateTime" },
    { name = "query_start_time_microseconds", type = "DateTime64(6)" },
    { name = "query_duration_ms", type = "UInt64" },
    { name = "read_rows", type = "UInt64" },
    { name = "read_bytes", type = "UInt64" },
    { name = "written_rows", type = "UInt64" },
    { name = "written_bytes", type = "UInt64" },
    { name = "result_rows", type = "UInt64" },
    { name = "result_bytes", type = "UInt64" },
    { name = "memory_usage", type = "UInt64" },
    { name = "peak_threads_usage", type = "UInt64" },
    { name = "current_database", type = "LowCardinality(String)" },
    { name = "query", type = "String" },
    { name = "formatted_query", type = "String" },
    { name = "normalized_query_hash", type = "UInt64" },
    { name = "query_kind", type = "LowCardinality(String)" },
    { name = "exception_code", type = "Int32" },
    { name = "exception_name", type = "String", alias_expression = "errorCodeToName(exception_code)" },
    { name = "exception", type = "String" },
    { name = "stack_trace", type = "String" },
    { name = "ProfileEvents_RealTimeMicroseconds", type = "Int64" },
    { name = "ProfileEvents_OSCPUVirtualTimeMicroseconds", type = "Int64" },
    { name = "ProfileEvents_S3Clients", type = "Int64" },
    { name = "ProfileEvents_S3DeleteObjects", type = "Int64" },
    { name = "ProfileEvents_S3CopyObject", type = "Int64" },
    { name = "ProfileEvents_S3ListObjects", type = "Int64" },
    { name = "ProfileEvents_S3HeadObject", type = "Int64" },
    { name = "ProfileEvents_S3GetObjectAttributes", type = "Int64" },
    { name = "ProfileEvents_S3CreateMultipartUpload", type = "Int64" },
    { name = "ProfileEvents_S3UploadPartCopy", type = "Int64" },
    { name = "ProfileEvents_S3UploadPart", type = "Int64" },
    { name = "ProfileEvents_S3AbortMultipartUpload", type = "Int64" },
    { name = "ProfileEvents_S3CompleteMultipartUpload", type = "Int64" },
    { name = "ProfileEvents_S3PutObject", type = "Int64" },
    { name = "ProfileEvents_S3GetObject", type = "Int64" },
    { name = "ProfileEvents_ReadBufferFromS3Bytes", type = "Int64" },
    { name = "ProfileEvents_WriteBufferFromS3Bytes", type = "Int64" },
    { name = "ProfileEvents", type = "Map(String, UInt64)" },
    { name = "lc_workflow", type = "LowCardinality(String)" },
    { name = "lc_kind", type = "LowCardinality(String)" },
    { name = "lc_id", type = "String" },
    { name = "lc_route_id", type = "String" },
    { name = "lc_access_method", type = "LowCardinality(String)" },
    { name = "lc_api_key_label", type = "String" },
    { name = "lc_api_key_mask", type = "String" },
    { name = "lc_query_type", type = "LowCardinality(String)" },
    { name = "lc_product", type = "LowCardinality(String)" },
    { name = "lc_chargeable", type = "Bool" },
    { name = "lc_name", type = "String" },
    { name = "lc_request_name", type = "String" },
    { name = "lc_client_query_id", type = "String" },
    { name = "lc_org_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "lc_user_id", type = "Int64" },
    { name = "lc_is_impersonated", type = "Bool" },
    { name = "lc_session_id", type = "String" },
    { name = "lc_dashboard_id", type = "Int64" },
    { name = "lc_insight_id", type = "Int64" },
    { name = "lc_cohort_id", type = "Int64" },
    { name = "lc_batch_export_id", type = "String" },
    { name = "lc_experiment_id", type = "Int64" },
    { name = "lc_experiment_feature_flag_key", type = "String" },
    { name = "lc_alert_config_id", type = "String" },
    { name = "lc_feature", type = "LowCardinality(String)" },
    { name = "lc_table_id", type = "String" },
    { name = "lc_warehouse_query", type = "Bool" },
    { name = "lc_person_on_events_mode", type = "LowCardinality(String)" },
    { name = "lc_service_name", type = "String" },
    { name = "lc_workload", type = "LowCardinality(String)" },
    { name = "lc_query__kind", type = "LowCardinality(String)" },
    { name = "lc_query__query", type = "String" },
    { name = "lc_query", type = "String" },
    { name = "lc_temporal__workflow_namespace", type = "String" },
    { name = "lc_temporal__workflow_type", type = "String" },
    { name = "lc_temporal__workflow_id", type = "String" },
    { name = "lc_temporal__workflow_run_id", type = "String" },
    { name = "lc_temporal__activity_type", type = "String" },
    { name = "lc_temporal__activity_id", type = "String" },
    { name = "lc_temporal__attempt", type = "Int64" },
    { name = "lc_dagster__job_name", type = "String" },
    { name = "lc_dagster__run_id", type = "String" },
    { name = "lc_dagster__owner", type = "String" },
    { name = "lc_modifiers", type = "String" },
  ]

  sharded_query_log_archive_columns = concat(local.query_log_archive_buffer_columns, [
    { name = "exception_name", type = "String", alias_expression = "errorCodeToName(exception_code)" },
    { name = "ProfileEvents_RealTimeMicroseconds", type = "Int64", alias_expression = "ProfileEvents['RealTimeMicroseconds']" },
    { name = "ProfileEvents_OSCPUVirtualTimeMicroseconds", type = "Int64", alias_expression = "ProfileEvents['OSCPUVirtualTimeMicroseconds']" },
    { name = "ProfileEvents_S3Clients", type = "Int64", alias_expression = "ProfileEvents['S3Clients']" },
    { name = "ProfileEvents_S3DeleteObjects", type = "Int64", alias_expression = "ProfileEvents['S3DeleteObjects']" },
    { name = "ProfileEvents_S3CopyObject", type = "Int64", alias_expression = "ProfileEvents['S3CopyObject']" },
    { name = "ProfileEvents_S3ListObjects", type = "Int64", alias_expression = "ProfileEvents['S3ListObjects']" },
    { name = "ProfileEvents_S3HeadObject", type = "Int64", alias_expression = "ProfileEvents['S3HeadObject']" },
    { name = "ProfileEvents_S3GetObjectAttributes", type = "Int64", alias_expression = "ProfileEvents['S3GetObjectAttributes']" },
    { name = "ProfileEvents_S3CreateMultipartUpload", type = "Int64", alias_expression = "ProfileEvents['S3CreateMultipartUpload']" },
    { name = "ProfileEvents_S3UploadPartCopy", type = "Int64", alias_expression = "ProfileEvents['S3UploadPartCopy']" },
    { name = "ProfileEvents_S3UploadPart", type = "Int64", alias_expression = "ProfileEvents['S3UploadPart']" },
    { name = "ProfileEvents_S3AbortMultipartUpload", type = "Int64", alias_expression = "ProfileEvents['S3AbortMultipartUpload']" },
    { name = "ProfileEvents_S3CompleteMultipartUpload", type = "Int64", alias_expression = "ProfileEvents['S3CompleteMultipartUpload']" },
    { name = "ProfileEvents_S3PutObject", type = "Int64", alias_expression = "ProfileEvents['S3PutObject']" },
    { name = "ProfileEvents_S3GetObject", type = "Int64", alias_expression = "ProfileEvents['S3GetObject']" },
    { name = "ProfileEvents_ReadBufferFromS3Bytes", type = "Int64", alias_expression = "ProfileEvents['ReadBufferFromS3Bytes']" },
    { name = "ProfileEvents_WriteBufferFromS3Bytes", type = "Int64", alias_expression = "ProfileEvents['WriteBufferFromS3Bytes']" },
    { name = "lc_workflow", type = "LowCardinality(String)", alias_expression = "log_comment.workflow" },
    { name = "lc_kind", type = "LowCardinality(String)", alias_expression = "log_comment.kind" },
    { name = "lc_id", type = "String", alias_expression = "CAST(log_comment.id, 'String')" },
    { name = "lc_route_id", type = "String", alias_expression = "CAST(log_comment.route_id, 'String')" },
    { name = "lc_access_method", type = "LowCardinality(String)", alias_expression = "log_comment.access_method" },
    { name = "lc_api_key_label", type = "String", alias_expression = "CAST(log_comment.api_key_label, 'String')" },
    { name = "lc_api_key_mask", type = "String", alias_expression = "CAST(log_comment.api_key_mask, 'String')" },
    { name = "lc_query_type", type = "LowCardinality(String)", alias_expression = "log_comment.query_type" },
    { name = "lc_product", type = "LowCardinality(String)", alias_expression = "log_comment.product" },
    { name = "lc_chargeable", type = "Bool", alias_expression = "log_comment.chargeable" },
    { name = "lc_name", type = "String", alias_expression = "CAST(log_comment.name, 'String')" },
    { name = "lc_request_name", type = "String", alias_expression = "CAST(log_comment.request_name, 'String')" },
    { name = "lc_client_query_id", type = "String", alias_expression = "CAST(log_comment.client_query_id, 'String')" },
    { name = "lc_org_id", type = "String", alias_expression = "CAST(log_comment.org_id, 'String')" },
    { name = "lc_user_id", type = "Int64", alias_expression = "log_comment.user_id" },
    { name = "lc_is_impersonated", type = "Bool", alias_expression = "log_comment.is_impersonated" },
    { name = "lc_session_id", type = "String", alias_expression = "CAST(log_comment.session_id, 'String')" },
    { name = "lc_dashboard_id", type = "Int64", alias_expression = "log_comment.dashboard_id" },
    { name = "lc_insight_id", type = "Int64", alias_expression = "log_comment.insight_id" },
    { name = "lc_cohort_id", type = "Int64", alias_expression = "log_comment.cohort_id" },
    { name = "lc_batch_export_id", type = "String", alias_expression = "CAST(log_comment.batch_export_id, 'String')" },
    { name = "lc_experiment_id", type = "Int64", alias_expression = "log_comment.experiment_id" },
    { name = "lc_experiment_feature_flag_key", type = "String", alias_expression = "CAST(log_comment.experiment_feature_flag_key, 'String')" },
    { name = "lc_alert_config_id", type = "String", alias_expression = "CAST(log_comment.alert_config_id, 'String')" },
    { name = "lc_feature", type = "LowCardinality(String)", alias_expression = "log_comment.feature" },
    { name = "lc_table_id", type = "String", alias_expression = "CAST(log_comment.table_id, 'String')" },
    { name = "lc_warehouse_query", type = "Bool", alias_expression = "log_comment.warehouse_query" },
    { name = "lc_person_on_events_mode", type = "LowCardinality(String)", alias_expression = "log_comment.person_on_events_mode" },
    { name = "lc_service_name", type = "String", alias_expression = "CAST(log_comment.service_name, 'String')" },
    { name = "lc_workload", type = "LowCardinality(String)", alias_expression = "log_comment.workload" },
    { name = "lc_query__kind", type = "LowCardinality(String)", alias_expression = "if(JSONHas(toString(log_comment), 'query', 'source'), JSONExtractString(toString(log_comment), 'query', 'source', 'kind'), JSONExtractString(toString(log_comment), 'query', 'kind'))" },
    { name = "lc_query__query", type = "String", alias_expression = "multiIf(NOT is_initial_query, '', JSONHas(toString(log_comment), 'query', 'source'), JSONExtractString(toString(log_comment), 'query', 'source', 'query'), JSONExtractString(toString(log_comment), 'query', 'query'))" },
    { name = "lc_query", type = "String", alias_expression = "if(is_initial_query, JSONExtractRaw(toString(log_comment), 'query'), '')" },
    { name = "lc_temporal__workflow_namespace", type = "String", alias_expression = "CAST(log_comment.`temporal.workflow_namespace`, 'String')" },
    { name = "lc_temporal__workflow_type", type = "String", alias_expression = "CAST(log_comment.`temporal.workflow_type`, 'String')" },
    { name = "lc_temporal__workflow_id", type = "String", alias_expression = "CAST(log_comment.`temporal.workflow_id`, 'String')" },
    { name = "lc_temporal__workflow_run_id", type = "String", alias_expression = "CAST(log_comment.`temporal.workflow_run_id`, 'String')" },
    { name = "lc_temporal__activity_type", type = "String", alias_expression = "CAST(log_comment.`temporal.activity_type`, 'String')" },
    { name = "lc_temporal__activity_id", type = "String", alias_expression = "CAST(log_comment.`temporal.activity_id`, 'String')" },
    { name = "lc_temporal__attempt", type = "Int64", alias_expression = "log_comment.`temporal.attempt`" },
    { name = "lc_dagster__job_name", type = "String", alias_expression = "CAST(log_comment.`dagster.job_name`, 'String')" },
    { name = "lc_dagster__run_id", type = "String", alias_expression = "CAST(log_comment.`dagster.run_id`, 'String')" },
    { name = "lc_dagster__owner", type = "String", alias_expression = "CAST(log_comment.`dagster.tags.owner`, 'String')" },
    { name = "lc_modifiers", type = "String", alias_expression = "if(is_initial_query, JSONExtractRaw(toString(log_comment), 'modifiers'), '')" },
    { name = "lc_plan_fingerprint", type = "String", alias_expression = "ifNull(dynamicElement(log_comment.plan_fingerprint, 'String'), '')" },
    { name = "lc_estimated_rows", type = "Int64", alias_expression = "ifNull(dynamicElement(log_comment.estimated_rows, 'Int64'), 0)" },
    { name = "lc_estimated_bytes", type = "Int64", alias_expression = "ifNull(dynamicElement(log_comment.estimated_bytes, 'Int64'), 0)" },
  ])
}

module "query_log_archive_v2_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "query_log_archive_v2"
  database = var.database
  layout   = "global"
  columns  = local.query_log_archive_v2_columns
  storage = {
    partition_by = "toYYYYMM(event_date)"
    order_by     = "(team_id, event_date, event_time, query_id)"
  }
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.query_log_archive_new"
  }, local.deployment)
}

module "sharded_query_log_archive_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "query_log_archive"
  database = var.database
  layout   = "global"
  columns  = local.sharded_query_log_archive_columns
  storage = {
    partition_by = "toYYYYMM(event_date)"
    order_by     = "(team_id, event_date, event_time, query_id)"
    settings     = "index_granularity = 8192, object_serialization_version = 'v3', object_shared_data_serialization_version = 'map_with_buckets'"
  }
  routing = {
    read         = true
    read_columns = local.sharded_query_log_archive_columns
  }
  deployment = merge({ cluster = "ops" }, local.deployment)
  names      = { storage = "sharded_query_log_archive" }
}

module "sharded_query_log_archive_old_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "query_log_archive_old"
  database = var.database
  columns  = local.query_log_archive_v2_columns
  storage = {
    partition_by = "toYYYYMM(event_date)"
    order_by     = "(team_id, event_date, event_time, query_id)"
  }
  routing = {
    read  = false
    write = false
  }
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.sharded_query_log_archive"
    cluster     = "posthog"
  }, local.deployment)
}

# Tables that hold data, and the materialized views between them.

module "ops_query_log_archive_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "ops_query_log_archive_mv")
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
  node   = var.node

  enabled  = contains(var.objects, "query_log_archive_buffer")
  database = var.database
  name     = "query_log_archive_buffer"
  engine   = "Buffer('posthog', 'sharded_query_log_archive', 16, 10, 60, 10000, 1000000, 10000000, 100000000)"
  columns  = local.query_log_archive_buffer_columns
  override = try(local.deployment.overrides["query_log_archive_buffer"], {})
}

# Distributed tables that inserts go through.

module "writable_query_log_archive" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "writable_query_log_archive")
  database = var.database
  name     = "writable_query_log_archive"
  engine   = "Distributed('ops', '${var.database}', 'query_log_archive_buffer')"
  columns  = local.query_log_archive_buffer_columns
  override = try(local.deployment.overrides["writable_query_log_archive"], {})
}
