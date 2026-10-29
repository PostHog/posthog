# The write path of the query_log_archive suite: the Distributed writer and the
# archiving MV. Split from qla.hcl because the local logs node runs only the
# query_log_archive table itself (it composes qla.hcl as a single-file layer).
database "posthog" {
  table "writable_query_log_archive_v3" {
    column "initial_query_start_time" {
      type = "DateTime64(6, 'UTC')"
    }
    column "team_id" {
      type = "Int64"
    }
    column "initial_query_id" {
      type = "String"
    }
    column "is_initial_query" {
      type = "SimpleAggregateFunction(max, UInt8)"
    }
    column "hostname" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "user" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "type" {
      type = "SimpleAggregateFunction(max, Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4))"
    }
    column "event_time_microseconds" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "query_duration_ms" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "read_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "read_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "written_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "written_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "result_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "result_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "memory_usage" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "memory_usage_sum" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "peak_threads_usage" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "execution_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "current_database" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "normalized_query_hash" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "query_kind_by_root" {
      type = "SimpleAggregateFunction(max, Tuple(UInt8, String))"
    }
    column "tables" {
      type = "SimpleAggregateFunction(max, Array(String))"
    }
    column "exception_code" {
      type = "SimpleAggregateFunction(max, Int32)"
    }
    column "exception" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "stack_trace" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "ProfileEvents_SelectedRows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_RealTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_OSCPUVirtualTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_UserTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SystemTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedParts" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedMarks" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_NetworkReceiveBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_NetworkSendBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_ReadBufferFromFileDescriptorReadBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_WriteBufferFromFileDescriptorWriteBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3Clients" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3DeleteObjects" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CopyObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3ListObjects" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3HeadObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3GetObjectAttributes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CreateMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3UploadPartCopy" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3UploadPart" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3AbortMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CompleteMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3PutObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3GetObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_ReadBufferFromS3Bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_WriteBufferFromS3Bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "lc_org_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_user_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_session_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_is_impersonated" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_workflow" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_kind" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_route_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_access_method" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_api_key_label" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_api_key_mask" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_query_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_product" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_chargeable" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_request_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_client_query_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_dashboard_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_insight_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_cohort_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_batch_export_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_experiment_feature_flag_key" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_alert_config_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_feature" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_table_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_warehouse_query" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_person_on_events_mode" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_service_name" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_workload" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_query__kind" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_query__query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_modifiers" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__workflow_namespace" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__workflow_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__workflow_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__workflow_run_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__activity_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__activity_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__attempt" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_dagster__job_name" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_dagster__run_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_dagster__owner" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_metric_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_execution_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_metric_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_funnel_order_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_exposures_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_metric_events_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_query_surface" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_precompute_table" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_query_group_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_precompute_skip_reason" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_scan_date_from" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_scan_date_to" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_precompute_window_start" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_precompute_window_end" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_plan_fingerprint" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_estimated_rows" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_estimated_bytes" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    engine "distributed" {
      cluster_name    = "ops"
      remote_database = "posthog"
      remote_table    = "query_log_archive_v3_buffer"
    }
  }
  materialized_view "ops_query_log_archive_v3_mv" {
    to_table = "posthog.writable_query_log_archive_v3"
    query = file("sql/ops_query_log_archive_v3_mv.sql")

    column "initial_query_start_time" {
      type = "DateTime64(6, 'UTC')"
    }
    column "team_id" {
      type = "Int64"
    }
    column "initial_query_id" {
      type = "String"
    }
    column "is_initial_query" {
      type = "SimpleAggregateFunction(max, UInt8)"
    }
    column "hostname" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "user" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "type" {
      type = "SimpleAggregateFunction(max, Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4))"
    }
    column "event_time_microseconds" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "query_duration_ms" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "read_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "read_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "written_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "written_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "result_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "result_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "memory_usage" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "memory_usage_sum" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "peak_threads_usage" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "execution_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "current_database" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "normalized_query_hash" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "query_kind_by_root" {
      type = "SimpleAggregateFunction(max, Tuple(UInt8, String))"
    }
    column "tables" {
      type = "SimpleAggregateFunction(max, Array(String))"
    }
    column "exception_code" {
      type = "SimpleAggregateFunction(max, Int32)"
    }
    column "exception" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "stack_trace" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "ProfileEvents_SelectedRows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_RealTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_OSCPUVirtualTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_UserTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SystemTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedParts" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedMarks" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_NetworkReceiveBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_NetworkSendBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_ReadBufferFromFileDescriptorReadBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_WriteBufferFromFileDescriptorWriteBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3Clients" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3DeleteObjects" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CopyObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3ListObjects" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3HeadObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3GetObjectAttributes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CreateMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3UploadPartCopy" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3UploadPart" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3AbortMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CompleteMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3PutObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3GetObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_ReadBufferFromS3Bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_WriteBufferFromS3Bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "lc_org_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_user_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_session_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_is_impersonated" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_workflow" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_kind" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_route_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_access_method" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_api_key_label" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_api_key_mask" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_query_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_product" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_chargeable" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_request_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_client_query_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_dashboard_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_insight_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_cohort_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_batch_export_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_experiment_feature_flag_key" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_alert_config_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_feature" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_table_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_warehouse_query" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_person_on_events_mode" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_service_name" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_workload" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_query__kind" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_query__query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_modifiers" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__workflow_namespace" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__workflow_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__workflow_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__workflow_run_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__activity_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__activity_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__attempt" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_dagster__job_name" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_dagster__run_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_dagster__owner" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_metric_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_execution_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_metric_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_funnel_order_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_exposures_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_metric_events_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_query_surface" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_precompute_table" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_query_group_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_precompute_skip_reason" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_scan_date_from" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_scan_date_to" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_precompute_window_start" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_precompute_window_end" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_plan_fingerprint" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_estimated_rows" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_estimated_bytes" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
  }
}
