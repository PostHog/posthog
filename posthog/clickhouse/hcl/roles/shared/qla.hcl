# Shared: query_log_archive read/write path + MV — present on every node role, every env

database "posthog" {
  table "query_log_archive" {
    column "hostname" {
      type = "LowCardinality(String)"
    }
    column "user" {
      type = "LowCardinality(String)"
    }
    column "query_id" {
      type = "String"
    }
    column "initial_query_id" {
      type = "String"
    }
    column "is_initial_query" {
      type = "UInt8"
    }
    column "type" {
      type = "Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4)"
    }
    column "event_date" {
      type = "Date"
    }
    column "event_time" {
      type = "DateTime"
    }
    column "event_time_microseconds" {
      type = "DateTime64(6)"
    }
    column "query_start_time" {
      type = "DateTime"
    }
    column "query_start_time_microseconds" {
      type = "DateTime64(6)"
    }
    column "query_duration_ms" {
      type = "UInt64"
    }
    column "read_rows" {
      type = "UInt64"
    }
    column "read_bytes" {
      type = "UInt64"
    }
    column "written_rows" {
      type = "UInt64"
    }
    column "written_bytes" {
      type = "UInt64"
    }
    column "result_rows" {
      type = "UInt64"
    }
    column "result_bytes" {
      type = "UInt64"
    }
    column "memory_usage" {
      type = "UInt64"
    }
    column "peak_threads_usage" {
      type = "UInt64"
    }
    column "current_database" {
      type = "LowCardinality(String)"
    }
    column "query" {
      type = "String"
    }
    column "formatted_query" {
      type = "String"
    }
    column "normalized_query_hash" {
      type = "UInt64"
    }
    column "query_kind" {
      type = "LowCardinality(String)"
    }
    column "exception_code" {
      type = "Int32"
    }
    column "exception" {
      type = "String"
    }
    column "stack_trace" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "log_comment" {
      type = "JSON(max_dynamic_paths=256, access_method LowCardinality(String), alert_config_id String, api_key_label String, api_key_mask String, batch_export_id String, chargeable Bool, client_query_id String, cohort_id Int64, `dagster.job_name` String, `dagster.run_id` String, `dagster.tags.owner` String, dashboard_id Int64, experiment_feature_flag_key String, experiment_id Int64, feature LowCardinality(String), id String, insight_id Int64, is_impersonated Bool, kind LowCardinality(String), name String, org_id String, person_on_events_mode LowCardinality(String), product LowCardinality(String), query_type LowCardinality(String), request_name String, route_id String, service_name String, session_id String, table_id String, team_id Int64, `temporal.activity_id` String, `temporal.activity_type` String, `temporal.attempt` Int64, `temporal.workflow_id` String, `temporal.workflow_namespace` String, `temporal.workflow_run_id` String, `temporal.workflow_type` String, user_id Int64, warehouse_query Bool, workflow LowCardinality(String), workload LowCardinality(String), SKIP cache_key, SKIP filter, SKIP hogql_features, SKIP http_referer, SKIP http_request_id, SKIP http_user_agent, SKIP query_settings, SKIP timings, SKIP user_email)"
    }
    column "ProfileEvents" {
      type = "Map(String, UInt64)"
    }
    column "exception_name" {
      type  = "String"
      alias = "errorCodeToName(exception_code)"
    }
    column "ProfileEvents_RealTimeMicroseconds" {
      type  = "Int64"
      alias = "ProfileEvents['RealTimeMicroseconds']"
    }
    column "ProfileEvents_OSCPUVirtualTimeMicroseconds" {
      type  = "Int64"
      alias = "ProfileEvents['OSCPUVirtualTimeMicroseconds']"
    }
    column "ProfileEvents_S3Clients" {
      type  = "Int64"
      alias = "ProfileEvents['S3Clients']"
    }
    column "ProfileEvents_S3DeleteObjects" {
      type  = "Int64"
      alias = "ProfileEvents['S3DeleteObjects']"
    }
    column "ProfileEvents_S3CopyObject" {
      type  = "Int64"
      alias = "ProfileEvents['S3CopyObject']"
    }
    column "ProfileEvents_S3ListObjects" {
      type  = "Int64"
      alias = "ProfileEvents['S3ListObjects']"
    }
    column "ProfileEvents_S3HeadObject" {
      type  = "Int64"
      alias = "ProfileEvents['S3HeadObject']"
    }
    column "ProfileEvents_S3GetObjectAttributes" {
      type  = "Int64"
      alias = "ProfileEvents['S3GetObjectAttributes']"
    }
    column "ProfileEvents_S3CreateMultipartUpload" {
      type  = "Int64"
      alias = "ProfileEvents['S3CreateMultipartUpload']"
    }
    column "ProfileEvents_S3UploadPartCopy" {
      type  = "Int64"
      alias = "ProfileEvents['S3UploadPartCopy']"
    }
    column "ProfileEvents_S3UploadPart" {
      type  = "Int64"
      alias = "ProfileEvents['S3UploadPart']"
    }
    column "ProfileEvents_S3AbortMultipartUpload" {
      type  = "Int64"
      alias = "ProfileEvents['S3AbortMultipartUpload']"
    }
    column "ProfileEvents_S3CompleteMultipartUpload" {
      type  = "Int64"
      alias = "ProfileEvents['S3CompleteMultipartUpload']"
    }
    column "ProfileEvents_S3PutObject" {
      type  = "Int64"
      alias = "ProfileEvents['S3PutObject']"
    }
    column "ProfileEvents_S3GetObject" {
      type  = "Int64"
      alias = "ProfileEvents['S3GetObject']"
    }
    column "ProfileEvents_ReadBufferFromS3Bytes" {
      type  = "Int64"
      alias = "ProfileEvents['ReadBufferFromS3Bytes']"
    }
    column "ProfileEvents_WriteBufferFromS3Bytes" {
      type  = "Int64"
      alias = "ProfileEvents['WriteBufferFromS3Bytes']"
    }
    column "lc_workflow" {
      type  = "LowCardinality(String)"
      alias = "log_comment.workflow"
    }
    column "lc_kind" {
      type  = "LowCardinality(String)"
      alias = "log_comment.kind"
    }
    column "lc_id" {
      type  = "String"
      alias = "CAST(log_comment.id, 'String')"
    }
    column "lc_route_id" {
      type  = "String"
      alias = "CAST(log_comment.route_id, 'String')"
    }
    column "lc_access_method" {
      type  = "LowCardinality(String)"
      alias = "log_comment.access_method"
    }
    column "lc_api_key_label" {
      type  = "String"
      alias = "CAST(log_comment.api_key_label, 'String')"
    }
    column "lc_api_key_mask" {
      type  = "String"
      alias = "CAST(log_comment.api_key_mask, 'String')"
    }
    column "lc_query_type" {
      type  = "LowCardinality(String)"
      alias = "log_comment.query_type"
    }
    column "lc_product" {
      type  = "LowCardinality(String)"
      alias = "log_comment.product"
    }
    column "lc_chargeable" {
      type  = "Bool"
      alias = "log_comment.chargeable"
    }
    column "lc_name" {
      type  = "String"
      alias = "CAST(log_comment.name, 'String')"
    }
    column "lc_request_name" {
      type  = "String"
      alias = "CAST(log_comment.request_name, 'String')"
    }
    column "lc_client_query_id" {
      type  = "String"
      alias = "CAST(log_comment.client_query_id, 'String')"
    }
    column "lc_org_id" {
      type  = "String"
      alias = "CAST(log_comment.org_id, 'String')"
    }
    column "lc_user_id" {
      type  = "Int64"
      alias = "log_comment.user_id"
    }
    column "lc_is_impersonated" {
      type  = "Bool"
      alias = "log_comment.is_impersonated"
    }
    column "lc_session_id" {
      type  = "String"
      alias = "CAST(log_comment.session_id, 'String')"
    }
    column "lc_dashboard_id" {
      type  = "Int64"
      alias = "log_comment.dashboard_id"
    }
    column "lc_insight_id" {
      type  = "Int64"
      alias = "log_comment.insight_id"
    }
    column "lc_cohort_id" {
      type  = "Int64"
      alias = "log_comment.cohort_id"
    }
    column "lc_batch_export_id" {
      type  = "String"
      alias = "CAST(log_comment.batch_export_id, 'String')"
    }
    column "lc_experiment_id" {
      type  = "Int64"
      alias = "log_comment.experiment_id"
    }
    column "lc_experiment_feature_flag_key" {
      type  = "String"
      alias = "CAST(log_comment.experiment_feature_flag_key, 'String')"
    }
    column "lc_alert_config_id" {
      type  = "String"
      alias = "CAST(log_comment.alert_config_id, 'String')"
    }
    column "lc_feature" {
      type  = "LowCardinality(String)"
      alias = "log_comment.feature"
    }
    column "lc_table_id" {
      type  = "String"
      alias = "CAST(log_comment.table_id, 'String')"
    }
    column "lc_warehouse_query" {
      type  = "Bool"
      alias = "log_comment.warehouse_query"
    }
    column "lc_person_on_events_mode" {
      type  = "LowCardinality(String)"
      alias = "log_comment.person_on_events_mode"
    }
    column "lc_service_name" {
      type  = "String"
      alias = "CAST(log_comment.service_name, 'String')"
    }
    column "lc_workload" {
      type  = "LowCardinality(String)"
      alias = "log_comment.workload"
    }
    column "lc_query__kind" {
      type  = "LowCardinality(String)"
      alias = "if(JSONHas(toString(log_comment), 'query', 'source'), JSONExtractString(toString(log_comment), 'query', 'source', 'kind'), JSONExtractString(toString(log_comment), 'query', 'kind'))"
    }
    column "lc_query__query" {
      type  = "String"
      alias = "multiIf(NOT is_initial_query, '', JSONHas(toString(log_comment), 'query', 'source'), JSONExtractString(toString(log_comment), 'query', 'source', 'query'), JSONExtractString(toString(log_comment), 'query', 'query'))"
    }
    column "lc_query" {
      type  = "String"
      alias = "if(is_initial_query, JSONExtractRaw(toString(log_comment), 'query'), '')"
    }
    column "lc_temporal__workflow_namespace" {
      type  = "String"
      alias = "CAST(log_comment.`temporal.workflow_namespace`, 'String')"
    }
    column "lc_temporal__workflow_type" {
      type  = "String"
      alias = "CAST(log_comment.`temporal.workflow_type`, 'String')"
    }
    column "lc_temporal__workflow_id" {
      type  = "String"
      alias = "CAST(log_comment.`temporal.workflow_id`, 'String')"
    }
    column "lc_temporal__workflow_run_id" {
      type  = "String"
      alias = "CAST(log_comment.`temporal.workflow_run_id`, 'String')"
    }
    column "lc_temporal__activity_type" {
      type  = "String"
      alias = "CAST(log_comment.`temporal.activity_type`, 'String')"
    }
    column "lc_temporal__activity_id" {
      type  = "String"
      alias = "CAST(log_comment.`temporal.activity_id`, 'String')"
    }
    column "lc_temporal__attempt" {
      type  = "Int64"
      alias = "log_comment.`temporal.attempt`"
    }
    column "lc_dagster__job_name" {
      type  = "String"
      alias = "CAST(log_comment.`dagster.job_name`, 'String')"
    }
    column "lc_dagster__run_id" {
      type  = "String"
      alias = "CAST(log_comment.`dagster.run_id`, 'String')"
    }
    column "lc_dagster__owner" {
      type  = "String"
      alias = "CAST(log_comment.`dagster.tags.owner`, 'String')"
    }
    column "lc_modifiers" {
      type  = "String"
      alias = "if(is_initial_query, JSONExtractRaw(toString(log_comment), 'modifiers'), '')"
    }
    engine "distributed" {
      cluster_name    = "ops"
      remote_database = "posthog"
      remote_table    = "sharded_query_log_archive"
    }
  }
  table "writable_query_log_archive" {
    column "hostname" {
      type = "LowCardinality(String)"
    }
    column "user" {
      type = "LowCardinality(String)"
    }
    column "query_id" {
      type = "String"
    }
    column "initial_query_id" {
      type = "String"
    }
    column "is_initial_query" {
      type = "UInt8"
    }
    column "type" {
      type = "Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4)"
    }
    column "event_date" {
      type = "Date"
    }
    column "event_time" {
      type = "DateTime"
    }
    column "event_time_microseconds" {
      type = "DateTime64(6)"
    }
    column "query_start_time" {
      type = "DateTime"
    }
    column "query_start_time_microseconds" {
      type = "DateTime64(6)"
    }
    column "query_duration_ms" {
      type = "UInt64"
    }
    column "read_rows" {
      type = "UInt64"
    }
    column "read_bytes" {
      type = "UInt64"
    }
    column "written_rows" {
      type = "UInt64"
    }
    column "written_bytes" {
      type = "UInt64"
    }
    column "result_rows" {
      type = "UInt64"
    }
    column "result_bytes" {
      type = "UInt64"
    }
    column "memory_usage" {
      type = "UInt64"
    }
    column "peak_threads_usage" {
      type = "UInt64"
    }
    column "current_database" {
      type = "LowCardinality(String)"
    }
    column "query" {
      type = "String"
    }
    column "formatted_query" {
      type = "String"
    }
    column "normalized_query_hash" {
      type = "UInt64"
    }
    column "query_kind" {
      type = "LowCardinality(String)"
    }
    column "exception_code" {
      type = "Int32"
    }
    column "exception" {
      type = "String"
    }
    column "stack_trace" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "log_comment" {
      type = "JSON(max_dynamic_paths=256, access_method LowCardinality(String), alert_config_id String, api_key_label String, api_key_mask String, batch_export_id String, chargeable Bool, client_query_id String, cohort_id Int64, `dagster.job_name` String, `dagster.run_id` String, `dagster.tags.owner` String, dashboard_id Int64, experiment_feature_flag_key String, experiment_id Int64, feature LowCardinality(String), id String, insight_id Int64, is_impersonated Bool, kind LowCardinality(String), name String, org_id String, person_on_events_mode LowCardinality(String), product LowCardinality(String), query_type LowCardinality(String), request_name String, route_id String, service_name String, session_id String, table_id String, team_id Int64, `temporal.activity_id` String, `temporal.activity_type` String, `temporal.attempt` Int64, `temporal.workflow_id` String, `temporal.workflow_namespace` String, `temporal.workflow_run_id` String, `temporal.workflow_type` String, user_id Int64, warehouse_query Bool, workflow LowCardinality(String), workload LowCardinality(String), SKIP cache_key, SKIP filter, SKIP hogql_features, SKIP http_referer, SKIP http_request_id, SKIP http_user_agent, SKIP query_settings, SKIP timings, SKIP user_email)"
    }
    column "ProfileEvents" {
      type = "Map(String, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "ops"
      remote_database = "posthog"
      remote_table    = "query_log_archive_buffer"
    }
  }
  materialized_view "ops_query_log_archive_mv" {
    to_table = "posthog.writable_query_log_archive"
    query = file("sql/ops_query_log_archive_mv.sql")
    column "hostname" {
      type = "LowCardinality(String)"
    }
    column "user" {
      type = "LowCardinality(String)"
    }
    column "query_id" {
      type = "String"
    }
    column "initial_query_id" {
      type = "String"
    }
    column "is_initial_query" {
      type = "UInt8"
    }
    column "type" {
      type = "Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4)"
    }
    column "event_date" {
      type = "Date"
    }
    column "event_time" {
      type = "DateTime"
    }
    column "event_time_microseconds" {
      type = "DateTime64(6)"
    }
    column "query_start_time" {
      type = "DateTime"
    }
    column "query_start_time_microseconds" {
      type = "DateTime64(6)"
    }
    column "query_duration_ms" {
      type = "UInt64"
    }
    column "read_rows" {
      type = "UInt64"
    }
    column "read_bytes" {
      type = "UInt64"
    }
    column "written_rows" {
      type = "UInt64"
    }
    column "written_bytes" {
      type = "UInt64"
    }
    column "result_rows" {
      type = "UInt64"
    }
    column "result_bytes" {
      type = "UInt64"
    }
    column "memory_usage" {
      type = "UInt64"
    }
    column "peak_threads_usage" {
      type = "UInt64"
    }
    column "current_database" {
      type = "LowCardinality(String)"
    }
    column "query" {
      type = "String"
    }
    column "formatted_query" {
      type = "String"
    }
    column "normalized_query_hash" {
      type = "UInt64"
    }
    column "query_kind" {
      type = "LowCardinality(String)"
    }
    column "exception_code" {
      type = "Int32"
    }
    column "exception" {
      type = "String"
    }
    column "stack_trace" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "log_comment" {
      type = "String"
    }
    column "ProfileEvents" {
      type = "Map(LowCardinality(String), UInt64)"
    }
  }
}
