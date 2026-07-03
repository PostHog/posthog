database "posthog" {
  table "ai_events" {
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
    engine "distributed" {
      cluster_name    = "ai_events"
      remote_database = "posthog"
      remote_table    = "sharded_ai_events"
      sharding_key    = "cityHash64(concat(toString(team_id), '-', trace_id, '-', toString(toDate(timestamp))))"
    }
  }

  table "kafka_ai_events_json" {
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
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_ai_events_json'"
      group_name  = "kafka_group_name = 'group1'"
      format      = "kafka_format = 'JSONEachRow'"
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

  table "sharded_ai_events" {
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
      zoo_path     = "/clickhouse/tables/{shard}/posthog.ai_events"
      replica_name = "{replica}"
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

  materialized_view "ai_events_json_mv" {
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
FROM posthog.kafka_ai_events_json AS src
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

  materialized_view "ops_query_log_archive_mv" {
    to_table = "posthog.writable_query_log_archive"
    query    = <<SQL
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

  view "custom_metrics_backups" {
    query = <<SQL
WITH
  ['ClickHouseCustomMetric_BackupFailed', 'ClickHouseCustomMetric_BackupSuccess', 'ClickHouseCustomMetric_BackupCancelled', 'ClickHouseCustomMetric_BackupAttempts'] AS names,
  [toInt64(countIf(status = 'BACKUP_FAILED')), toInt64(countIf(status = 'BACKUP_CREATED')), toInt64(countIf(status = 'BACKUP_CANCELLED')), toInt64(countIf(status = 'CREATING_BACKUP'))] AS values,
  ['Number of failed backups', 'Number of successful backups', 'Number of cancelled backups', 'Number of backup attempts'] AS descriptions,
  ['gauge', 'gauge', 'gauge', 'gauge'] AS types,
  arrayJoin(arrayZip(names, values, descriptions, types)) AS tpl
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
  [toInt64(countIf(create_time < (now() - toIntervalDay(15)))), maxIf(dateDiff('seconds', create_time, last_postpone_time), last_postpone_time != '1970-01-01'), maxIf(dateDiff('seconds', create_time, last_exception_time), (last_exception_time != '1970-01-01') AND (last_exception_time > (now() - toIntervalMinute(5))))] AS values,
  ['Number of entries that have been in the replication queue for more than 15 days', 'Maximum number of seconds that an entry has been postponed', 'Maximum number of seconds that an entry has been in error'] AS descriptions,
  ['gauge', 'gauge', 'gauge'] AS types,
  arrayJoin(arrayZip(names, values, descriptions, types)) AS tpl
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
