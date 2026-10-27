# OPS role — objects exclusive to the OPS node, all envs.

database "posthog" {
  table "events_team_daily_stats" {
    order_by = ["analysis_date", "team_id", "event"]
    settings = {
      index_granularity = "8192"
    }
    column "analysis_date" {
      type = "Date"
    }
    column "team_id" {
      type = "Int64"
    }
    column "event" {
      type = "String"
    }
    column "event_count" {
      type = "UInt64"
    }
    column "total_event_bytes" {
      type = "UInt64"
    }
    column "min_event_bytes" {
      type = "UInt64"
    }
    column "max_event_bytes" {
      type = "UInt64"
    }
    column "avg_event_bytes" {
      type = "Float64"
    }
    column "p50_event_bytes" {
      type = "Float64"
    }
    column "p90_event_bytes" {
      type = "Float64"
    }
    column "p95_event_bytes" {
      type = "Float64"
    }
    column "p99_event_bytes" {
      type = "Float64"
    }
    column "event_size_histogram" {
      type = "Array(Tuple(Float64, Float64, UInt64))"
    }
    column "computed_at" {
      type = "DateTime"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/ops/tables/{shard}/posthog.events_team_daily_stats"
      replica_name = "{replica}"
    }
  }
  table "query_log_archive_v3_buffer" {
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
    engine "buffer" {
      database   = "posthog"
      table      = "sharded_query_log_archive_v3"
      num_layers = 16
      min_time   = 10
      max_time   = 60
      min_rows   = 10000
      max_rows   = 1000000
      min_bytes  = 10000000
      max_bytes  = 100000000
    }
  }
  table "sharded_query_log_archive_v3" {
    order_by     = ["toStartOfHour(initial_query_start_time)", "team_id", "initial_query_start_time", "initial_query_id"]
    partition_by = "toYYYYMM(initial_query_start_time)"
    settings = {
      index_granularity = "8192"
    }
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
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "read_bytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "written_rows" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "written_bytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "result_rows" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "result_bytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "memory_usage" {
      type  = "SimpleAggregateFunction(max, UInt64)"
      codec = "T64, Default"
    }
    column "memory_usage_sum" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "peak_threads_usage" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "execution_count" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "current_database" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "query" {
      type = "SimpleAggregateFunction(max, String)"
      ttl  = "toDateTime(initial_query_start_time) + toIntervalMonth(3)"
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
      ttl  = "toDateTime(initial_query_start_time) + toIntervalMonth(3)"
    }
    column "stack_trace" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "ProfileEvents_SelectedRows" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_SelectedBytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_RealTimeMicroseconds" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_OSCPUVirtualTimeMicroseconds" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_UserTimeMicroseconds" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_SystemTimeMicroseconds" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_SelectedParts" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_SelectedMarks" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_NetworkReceiveBytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_NetworkSendBytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_ReadBufferFromFileDescriptorReadBytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_WriteBufferFromFileDescriptorWriteBytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3Clients" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3DeleteObjects" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3CopyObject" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3ListObjects" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3HeadObject" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3GetObjectAttributes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3CreateMultipartUpload" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3UploadPartCopy" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3UploadPart" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3AbortMultipartUpload" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3CompleteMultipartUpload" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3PutObject" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3GetObject" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_ReadBufferFromS3Bytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_WriteBufferFromS3Bytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
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
      ttl  = "toDateTime(initial_query_start_time) + toIntervalMonth(3)"
    }
    column "lc_query" {
      type = "SimpleAggregateFunction(max, String)"
      ttl  = "toDateTime(initial_query_start_time) + toIntervalMonth(3)"
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
    column "query_id" {
      type  = "String"
      alias = "initial_query_id"
    }
    column "event_time" {
      type  = "DateTime('UTC')"
      alias = "toDateTime(event_time_microseconds)"
    }
    column "event_date" {
      type  = "Date"
      alias = "toDate(event_time_microseconds)"
    }
    column "query_start_time" {
      type  = "DateTime('UTC')"
      alias = "toDateTime(initial_query_start_time)"
    }
    column "query_start_time_microseconds" {
      type  = "DateTime64(6, 'UTC')"
      alias = "initial_query_start_time"
    }
    column "query_kind" {
      type  = "LowCardinality(String)"
      alias = "tupleElement(query_kind_by_root, 2)"
    }
    column "formatted_query" {
      type  = "String"
      alias = "''"
    }
    column "query_shape" {
      type  = "String"
      alias = "normalizeQuery(query)"
    }
    column "hogql_shape" {
      type  = "String"
      alias = "normalizeQuery(lc_query__query)"
    }
    column "exception_name" {
      type  = "String"
      alias = "errorCodeToName(exception_code)"
    }
    column "ProfileEvents" {
      type  = "Map(String, UInt64)"
      alias = "map('SelectedRows', ProfileEvents_SelectedRows, 'SelectedBytes', ProfileEvents_SelectedBytes, 'RealTimeMicroseconds', ProfileEvents_RealTimeMicroseconds, 'OSCPUVirtualTimeMicroseconds', ProfileEvents_OSCPUVirtualTimeMicroseconds, 'UserTimeMicroseconds', ProfileEvents_UserTimeMicroseconds, 'SystemTimeMicroseconds', ProfileEvents_SystemTimeMicroseconds, 'SelectedParts', ProfileEvents_SelectedParts, 'SelectedMarks', ProfileEvents_SelectedMarks, 'NetworkReceiveBytes', ProfileEvents_NetworkReceiveBytes, 'NetworkSendBytes', ProfileEvents_NetworkSendBytes, 'ReadBufferFromFileDescriptorReadBytes', ProfileEvents_ReadBufferFromFileDescriptorReadBytes, 'WriteBufferFromFileDescriptorWriteBytes', ProfileEvents_WriteBufferFromFileDescriptorWriteBytes, 'S3Clients', ProfileEvents_S3Clients, 'S3DeleteObjects', ProfileEvents_S3DeleteObjects, 'S3CopyObject', ProfileEvents_S3CopyObject, 'S3ListObjects', ProfileEvents_S3ListObjects, 'S3HeadObject', ProfileEvents_S3HeadObject, 'S3GetObjectAttributes', ProfileEvents_S3GetObjectAttributes, 'S3CreateMultipartUpload', ProfileEvents_S3CreateMultipartUpload, 'S3UploadPartCopy', ProfileEvents_S3UploadPartCopy, 'S3UploadPart', ProfileEvents_S3UploadPart, 'S3AbortMultipartUpload', ProfileEvents_S3AbortMultipartUpload, 'S3CompleteMultipartUpload', ProfileEvents_S3CompleteMultipartUpload, 'S3PutObject', ProfileEvents_S3PutObject, 'S3GetObject', ProfileEvents_S3GetObject, 'ReadBufferFromS3Bytes', ProfileEvents_ReadBufferFromS3Bytes, 'WriteBufferFromS3Bytes', ProfileEvents_WriteBufferFromS3Bytes)"
    }
    index "initial_query_start_time_minmax" {
      expr        = "initial_query_start_time"
      type        = "minmax"
      granularity = 1
    }
    index "event_date_minmax" {
      expr        = "toDate(event_time_microseconds)"
      type        = "minmax"
      granularity = 1
    }
    index "event_time_minmax" {
      expr        = "toDateTime(event_time_microseconds)"
      type        = "minmax"
      granularity = 1
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.sharded_query_log_archive_v3_by_chain"
      replica_name = "{replica}"
    }
  }
}
