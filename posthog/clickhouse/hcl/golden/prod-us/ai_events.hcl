database "posthog" {
  table "ai_events" {
    order_by     = ["team_id", "trace_id", "timestamp"]
    partition_by = "toYYYYMM(drop_date)"
    ttl          = "drop_date"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "LowCardinality(String)"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    column "properties" {
      type = "String"
    }
    column "retention_days" {
      type    = "Int16"
      default = "30"
    }
    column "drop_date" {
      type         = "Date"
      materialized = "toDate(timestamp) + toIntervalDay(retention_days)"
    }
    column "trace_id" {
      type = "String"
    }
    column "session_id" {
      type = "Nullable(String)"
    }
    column "parent_id" {
      type = "Nullable(String)"
    }
    column "span_id" {
      type = "Nullable(String)"
    }
    column "span_type" {
      type = "LowCardinality(Nullable(String))"
    }
    column "generation_id" {
      type = "Nullable(String)"
    }
    column "experiment_id" {
      type = "Nullable(String)"
    }
    column "span_name" {
      type = "Nullable(String)"
    }
    column "trace_name" {
      type = "Nullable(String)"
    }
    column "prompt_name" {
      type = "Nullable(String)"
    }
    column "model" {
      type = "LowCardinality(Nullable(String))"
    }
    column "provider" {
      type = "LowCardinality(Nullable(String))"
    }
    column "framework" {
      type = "LowCardinality(Nullable(String))"
    }
    column "total_tokens" {
      type = "Nullable(Int64)"
    }
    column "input_tokens" {
      type = "Nullable(Int64)"
    }
    column "output_tokens" {
      type = "Nullable(Int64)"
    }
    column "text_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "text_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "image_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "image_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "audio_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "audio_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "video_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "video_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "reasoning_tokens" {
      type = "Nullable(Int64)"
    }
    column "cache_read_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "cache_creation_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "web_search_count" {
      type = "Nullable(Int64)"
    }
    column "input_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "output_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "total_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "request_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "web_search_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "audio_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "image_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "video_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "latency" {
      type = "Nullable(Float64)"
    }
    column "time_to_first_token" {
      type = "Nullable(Float64)"
    }
    column "is_error" {
      type = "UInt8"
    }
    column "error" {
      type = "Nullable(String)"
    }
    column "error_type" {
      type = "LowCardinality(Nullable(String))"
    }
    column "error_normalized" {
      type = "Nullable(String)"
    }
    column "input" {
      type = "Nullable(String)"
    }
    column "output" {
      type = "Nullable(String)"
    }
    column "output_choices" {
      type = "Nullable(String)"
    }
    column "input_state" {
      type = "Nullable(String)"
    }
    column "output_state" {
      type = "Nullable(String)"
    }
    column "tools" {
      type = "Nullable(String)"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_partition" {
      type = "UInt64"
    }
    index "idx_trace_id" {
      expr        = "trace_id"
      type        = "bloom_filter(0.001)"
      granularity = 1
    }
    index "idx_session_id" {
      expr        = "session_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_parent_id" {
      expr        = "parent_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_span_id" {
      expr        = "span_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_prompt_name" {
      expr        = "prompt_name"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_model" {
      expr        = "model"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_experiment_id" {
      expr        = "experiment_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_event" {
      expr        = "event"
      type        = "set(20)"
      granularity = 1
    }
    index "idx_is_error" {
      expr        = "is_error"
      type        = "set(2)"
      granularity = 1
    }
    index "idx_provider" {
      expr        = "provider"
      type        = "set(50)"
      granularity = 1
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/ai_events/tables/{shard}/posthog.ai_events"
      replica_name = "{replica}"
    }
  }

  table "kafka_ai_events_json_ws" {
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "elements_chain" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "person_id" {
      type = "UUID"
    }
    column "person_properties" {
      type = "String"
    }
    column "person_created_at" {
      type = "DateTime64(3)"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    engine "kafka" {
      collection           = "warpstream_ingestion"
      topic_list           = "clickhouse_ai_events_json"
      group_name           = "clickhouse_ai_events_ws"
      format               = "JSONEachRow"
      num_consumers        = 16
      max_block_size       = 5000
      skip_broken_messages = 100
      poll_timeout_ms      = 10000
      thread_per_consumer  = true
    }
  }

  table "person" {
    column "id" {
      type = "UUID"
    }
    column "created_at" {
      type = "DateTime64(3)"
    }
    column "team_id" {
      type = "Int64"
    }
    column "properties" {
      type = "String"
    }
    column "is_identified" {
      type = "Int8"
    }
    column "is_deleted" {
      type = "Int8"
    }
    column "version" {
      type = "UInt64"
    }
    column "last_seen_at" {
      type = "Nullable(DateTime64(3))"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "person"
    }
  }

  table "person_distinct_id2" {
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    column "is_deleted" {
      type = "Int8"
    }
    column "version" {
      type = "Int64"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "person_distinct_id2"
    }
  }

  table "query_log_archive" {
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
    column "query_id" {
      type = "String"
    }
    column "event_time" {
      type = "DateTime('UTC')"
    }
    column "event_date" {
      type = "Date"
    }
    column "query_start_time" {
      type = "DateTime('UTC')"
    }
    column "query_start_time_microseconds" {
      type = "DateTime64(6, 'UTC')"
    }
    column "query_kind" {
      type = "LowCardinality(String)"
    }
    column "formatted_query" {
      type = "String"
    }
    column "query_shape" {
      type = "String"
    }
    column "hogql_shape" {
      type = "String"
    }
    column "exception_name" {
      type = "String"
    }
    column "ProfileEvents" {
      type = "Map(String, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "ops"
      remote_database = "posthog"
      remote_table    = "sharded_query_log_archive_v3"
    }
  }

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

  materialized_view "ai_events_json_ws_mv" {
    to_table = "posthog.ai_events"
    query    = <<SQL
SELECT
  uuid,
  event,
  timestamp,
  team_id,
  distinct_id,
  person_id,
  concat(
    '{',
    arrayStringConcat(
      arrayMap(
        x -> concat('"', x.1, '":', x.2),
        arrayFilter(
          x -> ((x.1) NOT IN ('$ai_input', '$ai_output', '$ai_output_choices', '$ai_input_state', '$ai_output_state', '$ai_tools')),
          JSONExtractKeysAndValuesRaw(src.properties)
        )
      ),
      ','
    ),
    '}'
  ) AS properties,
  JSONExtractString(src.properties, '$ai_trace_id') AS trace_id,
  JSONExtract(src.properties, '$ai_session_id', 'Nullable(String)') AS session_id,
  JSONExtract(src.properties, '$ai_parent_id', 'Nullable(String)') AS parent_id,
  JSONExtract(src.properties, '$ai_span_id', 'Nullable(String)') AS span_id,
  JSONExtract(src.properties, '$ai_span_type', 'Nullable(String)') AS span_type,
  JSONExtract(src.properties, '$ai_generation_id', 'Nullable(String)') AS generation_id,
  JSONExtract(src.properties, '$ai_experiment_id', 'Nullable(String)') AS experiment_id,
  JSONExtract(src.properties, '$ai_span_name', 'Nullable(String)') AS span_name,
  JSONExtract(src.properties, '$ai_trace_name', 'Nullable(String)') AS trace_name,
  JSONExtract(src.properties, '$ai_prompt_name', 'Nullable(String)') AS prompt_name,
  JSONExtract(src.properties, '$ai_model', 'Nullable(String)') AS model,
  JSONExtract(src.properties, '$ai_provider', 'Nullable(String)') AS provider,
  JSONExtract(src.properties, '$ai_framework', 'Nullable(String)') AS framework,
  JSONExtract(src.properties, '$ai_total_tokens', 'Nullable(Int64)') AS total_tokens,
  JSONExtract(src.properties, '$ai_input_tokens', 'Nullable(Int64)') AS input_tokens,
  JSONExtract(src.properties, '$ai_output_tokens', 'Nullable(Int64)') AS output_tokens,
  JSONExtract(src.properties, '$ai_text_input_tokens', 'Nullable(Int64)') AS text_input_tokens,
  JSONExtract(src.properties, '$ai_text_output_tokens', 'Nullable(Int64)') AS text_output_tokens,
  JSONExtract(src.properties, '$ai_image_input_tokens', 'Nullable(Int64)') AS image_input_tokens,
  JSONExtract(src.properties, '$ai_image_output_tokens', 'Nullable(Int64)') AS image_output_tokens,
  JSONExtract(src.properties, '$ai_audio_input_tokens', 'Nullable(Int64)') AS audio_input_tokens,
  JSONExtract(src.properties, '$ai_audio_output_tokens', 'Nullable(Int64)') AS audio_output_tokens,
  JSONExtract(src.properties, '$ai_video_input_tokens', 'Nullable(Int64)') AS video_input_tokens,
  JSONExtract(src.properties, '$ai_video_output_tokens', 'Nullable(Int64)') AS video_output_tokens,
  JSONExtract(src.properties, '$ai_reasoning_tokens', 'Nullable(Int64)') AS reasoning_tokens,
  JSONExtract(src.properties, '$ai_cache_read_input_tokens', 'Nullable(Int64)') AS cache_read_input_tokens,
  JSONExtract(src.properties, '$ai_cache_creation_input_tokens', 'Nullable(Int64)') AS cache_creation_input_tokens,
  JSONExtract(src.properties, '$ai_web_search_count', 'Nullable(Int64)') AS web_search_count,
  JSONExtract(src.properties, '$ai_input_cost_usd', 'Nullable(Float64)') AS input_cost_usd,
  JSONExtract(src.properties, '$ai_output_cost_usd', 'Nullable(Float64)') AS output_cost_usd,
  JSONExtract(src.properties, '$ai_total_cost_usd', 'Nullable(Float64)') AS total_cost_usd,
  JSONExtract(src.properties, '$ai_request_cost_usd', 'Nullable(Float64)') AS request_cost_usd,
  JSONExtract(src.properties, '$ai_web_search_cost_usd', 'Nullable(Float64)') AS web_search_cost_usd,
  JSONExtract(src.properties, '$ai_audio_cost_usd', 'Nullable(Float64)') AS audio_cost_usd,
  JSONExtract(src.properties, '$ai_image_cost_usd', 'Nullable(Float64)') AS image_cost_usd,
  JSONExtract(src.properties, '$ai_video_cost_usd', 'Nullable(Float64)') AS video_cost_usd,
  JSONExtract(src.properties, '$ai_latency', 'Nullable(Float64)') AS latency,
  JSONExtract(src.properties, '$ai_time_to_first_token', 'Nullable(Float64)') AS time_to_first_token,
  if((JSONExtractRaw(src.properties, '$ai_is_error') IN ('true', '"true"')), 1, 0) AS is_error,
  JSONExtract(src.properties, '$ai_error', 'Nullable(String)') AS error,
  JSONExtract(src.properties, '$ai_error_type', 'Nullable(String)') AS error_type,
  JSONExtract(src.properties, '$ai_error_normalized', 'Nullable(String)') AS error_normalized,
  nullIf(JSONExtractRaw(src.properties, '$ai_input'), '') AS input,
  nullIf(JSONExtractRaw(src.properties, '$ai_output'), '') AS output,
  nullIf(JSONExtractRaw(src.properties, '$ai_output_choices'), '') AS output_choices,
  nullIf(JSONExtractRaw(src.properties, '$ai_input_state'), '') AS input_state,
  nullIf(JSONExtractRaw(src.properties, '$ai_output_state'), '') AS output_state,
  nullIf(JSONExtractRaw(src.properties, '$ai_tools'), '') AS tools,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_ai_events_json_ws AS src
SQL

    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    column "properties" {
      type = "String"
    }
    column "trace_id" {
      type = "String"
    }
    column "session_id" {
      type = "Nullable(String)"
    }
    column "parent_id" {
      type = "Nullable(String)"
    }
    column "span_id" {
      type = "Nullable(String)"
    }
    column "span_type" {
      type = "Nullable(String)"
    }
    column "generation_id" {
      type = "Nullable(String)"
    }
    column "experiment_id" {
      type = "Nullable(String)"
    }
    column "span_name" {
      type = "Nullable(String)"
    }
    column "trace_name" {
      type = "Nullable(String)"
    }
    column "prompt_name" {
      type = "Nullable(String)"
    }
    column "model" {
      type = "Nullable(String)"
    }
    column "provider" {
      type = "Nullable(String)"
    }
    column "framework" {
      type = "Nullable(String)"
    }
    column "total_tokens" {
      type = "Nullable(Int64)"
    }
    column "input_tokens" {
      type = "Nullable(Int64)"
    }
    column "output_tokens" {
      type = "Nullable(Int64)"
    }
    column "text_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "text_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "image_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "image_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "audio_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "audio_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "video_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "video_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "reasoning_tokens" {
      type = "Nullable(Int64)"
    }
    column "cache_read_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "cache_creation_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "web_search_count" {
      type = "Nullable(Int64)"
    }
    column "input_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "output_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "total_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "request_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "web_search_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "audio_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "image_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "video_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "latency" {
      type = "Nullable(Float64)"
    }
    column "time_to_first_token" {
      type = "Nullable(Float64)"
    }
    column "is_error" {
      type = "UInt8"
    }
    column "error" {
      type = "Nullable(String)"
    }
    column "error_type" {
      type = "Nullable(String)"
    }
    column "error_normalized" {
      type = "Nullable(String)"
    }
    column "input" {
      type = "Nullable(String)"
    }
    column "output" {
      type = "Nullable(String)"
    }
    column "output_choices" {
      type = "Nullable(String)"
    }
    column "input_state" {
      type = "Nullable(String)"
    }
    column "output_state" {
      type = "Nullable(String)"
    }
    column "tools" {
      type = "Nullable(String)"
    }
    column "_timestamp" {
      type = "Nullable(DateTime)"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_partition" {
      type = "UInt64"
    }
  }

  materialized_view "ops_query_log_archive_v3_mv" {
    to_table = "posthog.writable_query_log_archive_v3"
    query    = <<SQL
WITH
  JSONExtract(ql.log_comment, 'Tuple(team_id Int64, org_id String, user_id Int64, session_id String, is_impersonated Bool, workflow String, kind String, id String, route_id String, access_method String, api_key_label String, api_key_mask String, query_type String, product String, chargeable Bool, name String, request_name String, client_query_id String, dashboard_id Int64, insight_id Int64, cohort_id Int64, batch_export_id String, experiment_id Int64, experiment_feature_flag_key String, alert_config_id String, feature String, table_id String, warehouse_query Bool, person_on_events_mode String, service_name String, workload String, experiment_name String, experiment_metric_name String, experiment_execution_path String, experiment_metric_type String, experiment_funnel_order_type String, experiment_exposures_path String, experiment_metric_events_path String, experiment_query_surface String, experiment_precompute_table String, experiment_query_group_id String, experiment_precompute_skip_reason String, experiment_scan_date_from String, experiment_scan_date_to String, precompute_window_start String, precompute_window_end String, plan_fingerprint String, estimated_rows Int64, estimated_bytes Int64, temporal Tuple(workflow_namespace String, workflow_type String, workflow_id String, workflow_run_id String, activity_type String, activity_id String, attempt Int64), dagster Tuple(job_name String, run_id String, tags Tuple(owner String)), query Tuple(kind String, query String, source Tuple(kind String, query String)))') AS lc
SELECT
  if(
    empty(ql.initial_query_id),
    ql.query_start_time_microseconds,
    ql.initial_query_start_time_microseconds
  ) AS initial_query_start_time,
  lc.team_id AS team_id,
  if(empty(ql.initial_query_id), ql.query_id, ql.initial_query_id) AS initial_query_id,
  ql.is_initial_query AS is_initial_query,
  if(ql.is_initial_query, ql.hostname, '') AS hostname,
  ql.user AS user,
  ql.type AS type,
  ql.event_time_microseconds AS event_time_microseconds,
  if(ql.is_initial_query, ql.query_duration_ms, 0) AS query_duration_ms,
  if(ql.is_initial_query, ql.read_rows, 0) AS read_rows,
  if(ql.is_initial_query, ql.read_bytes, 0) AS read_bytes,
  if(ql.is_initial_query, ql.written_rows, 0) AS written_rows,
  if(ql.is_initial_query, ql.written_bytes, 0) AS written_bytes,
  if(ql.is_initial_query, ql.result_rows, 0) AS result_rows,
  if(ql.is_initial_query, ql.result_bytes, 0) AS result_bytes,
  ql.memory_usage AS memory_usage,
  ql.memory_usage AS memory_usage_sum,
  ql.peak_threads_usage AS peak_threads_usage,
  1 AS execution_count,
  ql.current_database AS current_database,
  if(ql.is_initial_query, ql.query, '') AS query,
  if(ql.is_initial_query, ql.normalized_query_hash, 0) AS normalized_query_hash,
  tuple(ql.is_initial_query, ql.query_kind) AS query_kind_by_root,
  if(ql.is_initial_query, ql.tables, []) AS tables,
  if(ql.is_initial_query, ql.exception_code, 0) AS exception_code,
  if(ql.is_initial_query, ql.exception, '') AS exception,
  if(ql.is_initial_query, ql.stack_trace, '') AS stack_trace,
  if(ql.is_initial_query, ql.ProfileEvents['SelectedRows'], 0) AS ProfileEvents_SelectedRows,
  if(ql.is_initial_query, ql.ProfileEvents['SelectedBytes'], 0) AS ProfileEvents_SelectedBytes,
  ql.ProfileEvents['RealTimeMicroseconds'] AS ProfileEvents_RealTimeMicroseconds,
  ql.ProfileEvents['OSCPUVirtualTimeMicroseconds'] AS ProfileEvents_OSCPUVirtualTimeMicroseconds,
  ql.ProfileEvents['UserTimeMicroseconds'] AS ProfileEvents_UserTimeMicroseconds,
  ql.ProfileEvents['SystemTimeMicroseconds'] AS ProfileEvents_SystemTimeMicroseconds,
  ql.ProfileEvents['SelectedParts'] AS ProfileEvents_SelectedParts,
  ql.ProfileEvents['SelectedMarks'] AS ProfileEvents_SelectedMarks,
  ql.ProfileEvents['NetworkReceiveBytes'] AS ProfileEvents_NetworkReceiveBytes,
  ql.ProfileEvents['NetworkSendBytes'] AS ProfileEvents_NetworkSendBytes,
  ql.ProfileEvents['ReadBufferFromFileDescriptorReadBytes'] AS ProfileEvents_ReadBufferFromFileDescriptorReadBytes,
  ql.ProfileEvents['WriteBufferFromFileDescriptorWriteBytes'] AS ProfileEvents_WriteBufferFromFileDescriptorWriteBytes,
  ql.ProfileEvents['S3Clients'] AS ProfileEvents_S3Clients,
  ql.ProfileEvents['S3DeleteObjects'] AS ProfileEvents_S3DeleteObjects,
  ql.ProfileEvents['S3CopyObject'] AS ProfileEvents_S3CopyObject,
  ql.ProfileEvents['S3ListObjects'] AS ProfileEvents_S3ListObjects,
  ql.ProfileEvents['S3HeadObject'] AS ProfileEvents_S3HeadObject,
  ql.ProfileEvents['S3GetObjectAttributes'] AS ProfileEvents_S3GetObjectAttributes,
  ql.ProfileEvents['S3CreateMultipartUpload'] AS ProfileEvents_S3CreateMultipartUpload,
  ql.ProfileEvents['S3UploadPartCopy'] AS ProfileEvents_S3UploadPartCopy,
  ql.ProfileEvents['S3UploadPart'] AS ProfileEvents_S3UploadPart,
  ql.ProfileEvents['S3AbortMultipartUpload'] AS ProfileEvents_S3AbortMultipartUpload,
  ql.ProfileEvents['S3CompleteMultipartUpload'] AS ProfileEvents_S3CompleteMultipartUpload,
  ql.ProfileEvents['S3PutObject'] AS ProfileEvents_S3PutObject,
  ql.ProfileEvents['S3GetObject'] AS ProfileEvents_S3GetObject,
  ql.ProfileEvents['ReadBufferFromS3Bytes'] AS ProfileEvents_ReadBufferFromS3Bytes,
  ql.ProfileEvents['WriteBufferFromS3Bytes'] AS ProfileEvents_WriteBufferFromS3Bytes,
  lc.org_id AS lc_org_id,
  lc.user_id AS lc_user_id,
  lc.session_id AS lc_session_id,
  lc.is_impersonated AS lc_is_impersonated,
  lc.workflow AS lc_workflow,
  lc.kind AS lc_kind,
  lc.id AS lc_id,
  lc.route_id AS lc_route_id,
  lc.access_method AS lc_access_method,
  lc.api_key_label AS lc_api_key_label,
  lc.api_key_mask AS lc_api_key_mask,
  lc.query_type AS lc_query_type,
  lc.product AS lc_product,
  lc.chargeable AS lc_chargeable,
  lc.name AS lc_name,
  lc.request_name AS lc_request_name,
  lc.client_query_id AS lc_client_query_id,
  lc.dashboard_id AS lc_dashboard_id,
  lc.insight_id AS lc_insight_id,
  lc.cohort_id AS lc_cohort_id,
  lc.batch_export_id AS lc_batch_export_id,
  lc.experiment_id AS lc_experiment_id,
  lc.experiment_feature_flag_key AS lc_experiment_feature_flag_key,
  lc.alert_config_id AS lc_alert_config_id,
  lc.feature AS lc_feature,
  lc.table_id AS lc_table_id,
  lc.warehouse_query AS lc_warehouse_query,
  lc.person_on_events_mode AS lc_person_on_events_mode,
  lc.service_name AS lc_service_name,
  lc.workload AS lc_workload,
  if(notEmpty(lc.query.source.kind), lc.query.source.kind, lc.query.kind) AS lc_query__kind,
  if(
    ql.is_initial_query,
    if(notEmpty(lc.query.source.kind), lc.query.source.query, lc.query.query),
    ''
  ) AS lc_query__query,
  if(ql.is_initial_query, JSONExtractRaw(ql.log_comment, 'query'), '') AS lc_query,
  if(ql.is_initial_query, JSONExtractRaw(ql.log_comment, 'modifiers'), '') AS lc_modifiers,
  lc.temporal.workflow_namespace AS lc_temporal__workflow_namespace,
  lc.temporal.workflow_type AS lc_temporal__workflow_type,
  lc.temporal.workflow_id AS lc_temporal__workflow_id,
  lc.temporal.workflow_run_id AS lc_temporal__workflow_run_id,
  lc.temporal.activity_type AS lc_temporal__activity_type,
  lc.temporal.activity_id AS lc_temporal__activity_id,
  lc.temporal.attempt AS lc_temporal__attempt,
  lc.dagster.job_name AS lc_dagster__job_name,
  lc.dagster.run_id AS lc_dagster__run_id,
  lc.dagster.tags.owner AS lc_dagster__owner,
  lc.experiment_name AS lc_experiment_name,
  lc.experiment_metric_name AS lc_experiment_metric_name,
  lc.experiment_execution_path AS lc_experiment_execution_path,
  lc.experiment_metric_type AS lc_experiment_metric_type,
  lc.experiment_funnel_order_type AS lc_experiment_funnel_order_type,
  lc.experiment_exposures_path AS lc_experiment_exposures_path,
  lc.experiment_metric_events_path AS lc_experiment_metric_events_path,
  lc.experiment_query_surface AS lc_experiment_query_surface,
  lc.experiment_precompute_table AS lc_experiment_precompute_table,
  lc.experiment_query_group_id AS lc_experiment_query_group_id,
  lc.experiment_precompute_skip_reason AS lc_experiment_precompute_skip_reason,
  lc.experiment_scan_date_from AS lc_experiment_scan_date_from,
  lc.experiment_scan_date_to AS lc_experiment_scan_date_to,
  lc.precompute_window_start AS lc_precompute_window_start,
  lc.precompute_window_end AS lc_precompute_window_end,
  lc.plan_fingerprint AS lc_plan_fingerprint,
  lc.estimated_rows AS lc_estimated_rows,
  lc.estimated_bytes AS lc_estimated_bytes
FROM system.query_log AS ql
WHERE ql.type != 'QueryStart'
SQL

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

  view "custom_metrics" {
    query = <<SQL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_test
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_replication_queue
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_server_crash
UNION ALL
SELECT *
FROM posthog.custom_metrics_table_sizes
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_part_counts
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_dictionaries
UNION ALL
SELECT
  'ClickHouseCustomMetric_S3DiskBytesUsed' AS name,
  map('instance', hostname(), 'disk', disk_name) AS labels,
  toFloat64(sum(bytes_on_disk)) AS value,
  'Bytes currently used by ClickHouse parts on S3-backed disks on this node' AS help,
  'gauge' AS type
FROM system.parts
WHERE disk_name IN ('s3disk', 'cache')
GROUP BY
  disk_name
UNION ALL
SELECT
  'ClickHouseCustomMetric_MergeFailures15m' AS name,
  map('instance', hostname()) AS labels,
  toFloat64(count()) AS value,
  'Number of failed merge operations in the last 15 minutes' AS help,
  'gauge' AS type
FROM system.part_log
WHERE
  (event_time >= (now() - toIntervalMinute(15)))
AND
  (event_type = 'MergeParts')
AND
  (error > 0)
AND
  (merge_reason != 'NotAMerge')
AND
  (error != 40)
UNION ALL
SELECT
  'ClickHouseCustomMetric_MergeRetriesMaxPerTable15m' AS name,
  map('instance', hostname()) AS labels,
  toFloat64(max(cnt)) AS value,
  'Max failed merge retries for any single table in the last 15 minutes' AS help,
  'gauge' AS type
FROM
  (
    SELECT count() AS cnt
    FROM system.part_log
    WHERE
      (event_time >= (now() - toIntervalMinute(15)))
    AND
      (event_type = 'MergeParts')
    AND
      (error > 0)
    AND
      (merge_reason != 'NotAMerge')
    AND
      (error != 40)
    GROUP BY
      database, `table`, partition_id
  )
SQL

  }

  view "custom_metrics_backups" {
    query = <<SQL
WITH
  ['ClickHouseCustomMetric_BackupFailed', 'ClickHouseCustomMetric_BackupSuccess', 'ClickHouseCustomMetric_BackupCancelled', 'ClickHouseCustomMetric_BackupAttempts'] AS names,
  [toInt64(countIf(status = 'BACKUP_FAILED')), toInt64(countIf(status = 'BACKUP_CREATED')), toInt64(countIf(status = 'BACKUP_CANCELLED')), toInt64(countIf(status = 'CREATING_BACKUP'))] AS `values`,
  ['Number of failed backups', 'Number of successful backups', 'Number of cancelled backups', 'Number of backup attempts'] AS descriptions,
  ['gauge', 'gauge', 'gauge', 'gauge'] AS types,
  arrayJoin(arrayZip(names, `values`, descriptions, types)) AS tpl
SELECT
  tpl.1 AS name,
  map('instance', hostname()) AS labels,
  tpl.2 AS value,
  tpl.3 AS help,
  tpl.4 AS type
FROM system.backup_log
WHERE event_date = today()
GROUP BY
  event_date
SQL

  }

  view "custom_metrics_dictionaries" {
    query = <<SQL
SELECT
  'ClickHouseCustomMetric_DictionariesFailed' AS name,
  map(
    'instance',
    hostname(),
    'database',
    d.database,
    'dictionary',
    d.dict_name,
    'uuid',
    toString(d.uuid),
    'status',
    toString(d.status)
  ) AS labels,
  toUInt64(1) AS value,
  'Dictionary is in FAILED or FAILED_AND_RELOADING status' AS help,
  'gauge' AS type
FROM
  (
    SELECT name AS dict_name, database, uuid, status
    FROM system.dictionaries
    WHERE status IN ('FAILED', 'FAILED_AND_RELOADING')
  ) AS d
SQL

  }

  view "custom_metrics_part_counts" {
    query = <<SQL
SELECT
  'ClickHouseCustomMetric_MaxPartCountPerPartition' AS name,
  map('instance', hostname(), 'database', database, 'table', `table`, 'partition', partition) AS labels,
  part_count AS value,
  'Maximum number of active parts for any partition in a PostHog table' AS help,
  'gauge' AS type
FROM
  (
    SELECT database, `table`, partition, count() AS part_count
    FROM system.parts
    WHERE
      active
    AND
      (database = 'posthog')
    GROUP BY
      database, `table`, partition
    ORDER BY database ASC, `table` ASC, part_count DESC, partition ASC
    LIMIT 1 BY database, `table`
  )
SQL

  }

  view "custom_metrics_replication_queue" {
    query = <<SQL
WITH
  ['ClickHouseCustomMetric_ReplicationQueueStuckEntries', 'ClickHouseCustomMetric_ReplicationQueueMaxPostponedEntrySeconds', 'ClickHouseCustomMetric_ReplicationQueueMaxErrorEntrySeconds'] AS names,
  [toInt64(countIf(create_time < (now() - toIntervalDay(15)))), maxIf(dateDiff('seconds', create_time, last_postpone_time), last_postpone_time != '1970-01-01'), maxIf(dateDiff('seconds', create_time, last_exception_time), (last_exception_time != '1970-01-01') AND (last_exception_time > (now() - toIntervalMinute(5))))] AS `values`,
  ['Number of entries that have been in the replication queue for more than 15 days', 'Maximum number of seconds that an entry has been postponed', 'Maximum number of seconds that an entry has been in error'] AS descriptions,
  ['gauge', 'gauge', 'gauge'] AS types,
  arrayJoin(arrayZip(names, `values`, descriptions, types)) AS tpl
SELECT
  tpl.1 AS name,
  map('table', `table`, 'instance', hostname()) AS labels,
  tpl.2 AS value,
  tpl.3 AS help,
  tpl.4 AS type
FROM system.replication_queue
GROUP BY
  `table`
HAVING
  value > 0
SQL

  }

  view "custom_metrics_server_crash" {
    query = <<SQL
SELECT
  'ClickHouseCustomMetric_ServerCrash' AS name,
  map('instance', hostname()) AS labels,
  count() AS value,
  'Number of server crashes for current date' AS help,
  'gauge' AS type
FROM system.crash_log
WHERE event_date = today()
GROUP BY
  hostname()
SQL

  }

  view "custom_metrics_table_sizes" {
    query = <<SQL
SELECT
  'ClickHouseCustomMetric_TableTotalBytes' AS name,
  map('instance', hostname(), 'database', database, 'table', `table`) AS labels,
  CAST(total_bytes, 'Float64') AS value,
  'Size of a database table on a given node (need a sum for sharded)' AS help,
  'gauge' AS type
FROM system.tables
WHERE
  (database NOT IN ('INFORMATION_SCHEMA', 'information_schema'))
AND
  (total_bytes IS NOT NULL)
SQL

  }

  view "custom_metrics_test" {
    query = <<SQL
SELECT
  'ClickHouseCustomMetric_Test' AS name,
  map('instance', hostname()) AS labels,
  1 AS value,
  'Test to check that the metric endpoint is working' AS help,
  'gauge' AS type
SQL

  }
}

named_collection "msk_cluster" {
  external = true
}

named_collection "warpstream_calculated_events" {
  external = true
}

named_collection "warpstream_cyclotron" {
  external = true
}

named_collection "warpstream_ingestion" {
  external = true
}

named_collection "warpstream_logs" {
  external = true
}

named_collection "warpstream_metrics" {
  external = true
}

named_collection "warpstream_replay" {
  external = true
}

named_collection "warpstream_shared" {
  external = true
}

named_collection "warpstream_traces" {
  external = true
}
