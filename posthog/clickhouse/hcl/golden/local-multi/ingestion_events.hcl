node "events" {
  macros = {
    hostClusterRole = "events"
    hostClusterType = "online"
    replica         = "events"
    shard           = "01"
  }
}

database "posthog" {
  table "kafka_events_json_native_json" {
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type  = "String"
      codec = "ZSTD(3)"
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
    column "person_created_at" {
      type = "DateTime64(3)"
    }
    column "person_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group0_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group1_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group2_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group3_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group4_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group0_created_at" {
      type = "DateTime64(3)"
    }
    column "group1_created_at" {
      type = "DateTime64(3)"
    }
    column "group2_created_at" {
      type = "DateTime64(3)"
    }
    column "group3_created_at" {
      type = "DateTime64(3)"
    }
    column "group4_created_at" {
      type = "DateTime64(3)"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "historical_migration" {
      type = "Bool"
    }
    column "dmat_string_0" {
      type = "Nullable(String)"
    }
    column "dmat_string_1" {
      type = "Nullable(String)"
    }
    column "dmat_string_2" {
      type = "Nullable(String)"
    }
    column "dmat_string_3" {
      type = "Nullable(String)"
    }
    column "dmat_string_4" {
      type = "Nullable(String)"
    }
    column "dmat_string_5" {
      type = "Nullable(String)"
    }
    column "dmat_string_6" {
      type = "Nullable(String)"
    }
    column "dmat_string_7" {
      type = "Nullable(String)"
    }
    column "dmat_string_8" {
      type = "Nullable(String)"
    }
    column "dmat_string_9" {
      type = "Nullable(String)"
    }
    column "captured_at" {
      type = "Nullable(DateTime64(6, 'UTC'))"
    }
    engine "kafka" {
      broker_list          = "msk_cluster"
      topic_list           = "kafka_topic_list = 'clickhouse_events_json'"
      group_name           = "kafka_group_name = 'clickhouse_events_json_native_json'"
      format               = "kafka_format = 'JSONEachRow'"
      skip_broken_messages = 100
    }
  }

  table "kafka_logs_avro" {
    settings = {
      input_format_avro_allow_missing_fields = "1"
    }
    column "uuid" {
      type = "String"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "trace_flags" {
      type = "Int32"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "body" {
      type = "String"
    }
    column "severity_text" {
      type = "String"
    }
    column "severity_number" {
      type = "Int32"
    }
    column "service_name" {
      type = "String"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "event_name" {
      type = "String"
    }
    column "attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "retention_days" {
      type = "Nullable(Int32)"
    }
    column "pattern" {
      type = "Nullable(String)"
    }
    column "pattern_version" {
      type = "Nullable(Int32)"
    }
    engine "kafka" {
      broker_list          = "warpstream_logs"
      topic_list           = "kafka_topic_list = 'clickhouse_logs'"
      group_name           = "kafka_group_name = 'clickhouse-logs-avro-new'"
      format               = "kafka_format = 'Avro'"
      num_consumers        = 8
      skip_broken_messages = 100
      poll_timeout_ms      = 3000
      poll_max_batch_size  = 1000
      thread_per_consumer  = true
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

  table "writable_events_json" {
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "JSON(max_dynamic_paths=0, `$agent_application_id` String, `$agent_revision_id` String, `$agent_session_id` String, `$agent_turn` String, `$ai_audio_cost_usd` String, `$ai_audio_input_tokens` String, `$ai_audio_output_tokens` String, `$ai_batch_run_id` String, `$ai_cache_creation_input_tokens` String, `$ai_cache_read_input_tokens` String, `$ai_error` String, `$ai_error_normalized` String, `$ai_error_type` String, `$ai_evaluation_allows_na` String, `$ai_evaluation_applicable` String, `$ai_evaluation_id` String, `$ai_evaluation_name` String, `$ai_evaluation_reasoning` String, `$ai_evaluation_result` String, `$ai_evaluation_result_type` String, `$ai_evaluation_runtime` String, `$ai_evaluation_skipped` String, `$ai_evaluation_start_time` String, `$ai_evaluation_type` String, `$ai_experiment_id` String, `$ai_framework` String, `$ai_generation_id` String, `$ai_http_status` String, `$ai_image_cost_usd` String, `$ai_image_input_tokens` String, `$ai_image_output_tokens` String, `$ai_input_cost_usd` String, `$ai_input_tokens` String, `$ai_is_error` String, `$ai_latency` String, `$ai_model` String, `$ai_output_cost_usd` String, `$ai_output_tokens` String, `$ai_parent_id` String, `$ai_prompt_name` String, `$ai_provider` String, `$ai_reasoning_tokens` String, `$ai_request_cost_usd` String, `$ai_session_id` String, `$ai_span_name` String, `$ai_span_type` String, `$ai_span_id` String, `$ai_sentiment_label` String, `$ai_sentiment_message_count` String, `$ai_sentiment_score` String, `$ai_target_event_id` String, `$ai_text_input_tokens` String, `$ai_text_output_tokens` String, `$ai_time_to_first_token` String, `$ai_total_cost_usd` String, `$ai_total_tokens` String, `$ai_tools_called` String, `$ai_trace_id` String, `$ai_trace_name` String, `$ai_video_cost_usd` String, `$ai_video_input_tokens` String, `$ai_video_output_tokens` String, `$ai_web_search_cost_usd` String, `$ai_web_search_count` String, `$ai_origin` String, `$anon_distinct_id` String, `$app_build` String, `$app_name` String, `$app_namespace` String, `$app_version` String, `$browser` String, `$browser_language` String, `$browser_language_prefix` String, `$browser_type` String, `$browser_version` String, `$current_url` String, `$device` String, `$device_id` String, `$device_model` String, `$device_manufacturer` String, `$device_name` String, `$device_type` String, `$el_text` String, `$event_type` String, `$exception_fingerprint` String, `$exception_functions` Array(String), `$exception_handled` String, `$exception_is_synthetic` String, `$exception_issue_id` String, `$exception_level` String, `$exception_list` Array(JSON(max_dynamic_paths=0, type String, value String)), `$exception_message` String, `$exception_proposed_fingerprint` String, `$exception_sources` Array(String), `$exception_type` String, `$exception_types` Array(String), `$exception_values` Array(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_postal_code` String, `$geoip_subdivision_1_name` String, `$geoip_subdivision_2_code` String, `$geoip_subdivision_2_name` String, `$geoip_time_zone` LowCardinality(String), `$geoip_subdivision_1_code` String, `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$groups.organization` String, `$groups.project` String, `$groups.instance` String, `$group_set.icp_company_type` String, `$host` String, `$initial_pathname` String, `$initial_referrer` String, `$initial_referring_domain` String, `$client_session_initial_pathname` String, `$client_session_initial_referring_host` String, `$client_session_initial_utm_campaign` String, `$client_session_initial_utm_content` String, `$client_session_initial_utm_medium` String, `$client_session_initial_utm_source` String, `$client_session_initial_utm_term` String, `$initial_search_engine` String, `$ip` String, `$is_identified` String, `$lib` String, `$lib_custom_api_host` String, `$lib_version` String, `$lib_version__minor` String, `$mcp_client_name` String, `$mcp_client_user_agent` String, `$mcp_duration_ms` String, `$mcp_error_message` String, `$mcp_exec_tool_call_description` String, `$mcp_exec_tool_call_name` String, `$mcp_intent` String, `$mcp_intent_source` String, `$mcp_is_error` String, `$mcp_listed_tool_names` Array(String), `$mcp_oauth_client_name` String, `$mcp_organization_id` String, `$mcp_project_id` String, `$mcp_session_id` String, `$mcp_source` String, `$mcp_tool_category` String, `$mcp_tool_description` String, `$mcp_tool_name` String, `$os` String, `$os_name` String, `$os_version` String, `$pathname` String, `$prev_pageview_max_content_percentage` String, `$prev_pageview_max_scroll_percentage` String, `$prev_pageview_pathname` String, `$process_person_profile` String, `$recording_status` String, `$referrer` String, `$referring_domain` String, `$replay_minimum_duration` String, `$replay_sample_rate` String, `$raw_user_agent` String, `$search_engine` String, `$screen_height` String, `$screen_name` String, `$screen_width` String, `$sent_at` String, `$session_id` String, `$session_entry_host` String, `$session_entry_pathname` String, `$session_entry_referrer` String, `$session_entry_referring_domain` String, `$session_entry_search_engine` String, `$session_entry_url` String, `$session_entry_utm_campaign` String, `$session_entry_utm_content` String, `$session_entry_utm_medium` String, `$session_entry_utm_source` String, `$session_entry_utm_term` String, `$session_recording_event_trigger_activated_session` String, `$session_recording_start_reason` String, `$session_recording_url_trigger_status` String, `$sdk_debug_recording_script_not_loaded` String, `$survey_id` String, `$survey_completed` String, `$survey_iteration` String, `$survey_iteration_start_date` String, `$survey_name` String, `$survey_partially_completed` String, `$survey_response` String, `$survey_response_1` String, `$survey_submission_id` String, `$time` String, `$timezone` String, `$timezone_offset` String, `$user_id` String, `$viewport_height` String, `$viewport_width` String, `$web_vitals_CLS_value` String, `$web_vitals_FCP_value` String, `$web_vitals_INP_value` String, `$web_vitals_LCP_value` String, `$window_id` String, `Account.client_id` String, `Connection.app.name` String, `Event.productCode` String, `HTTP Method` String, `Plan type and filter` String, `Subscription.plan.amount` String, `action` String, `action_name` String, `address` String, `apiErrorMessage` String, `apiName` String, `app_name` String, `app_version` String, `arguments` String, `audio_duration` String, `authentication_method` String, `auto_chapters` String, `auto_highlights` String, `category` String, `chain` String, `channel` String, `client_id` String, `client_name` String, `commit_sha` String, `community_id` String, `conceptName` String, `content_length` String, `content_safety` String, `context` String, `contributionError` String, `created_at` String, `created_by` String, `created_by_system` String, `currentScreen` String, `current_member_guid` String, `customer_email` String, `deal_id` String, `device_type` String, `disable_institution_search` String, `disfluencies` String, `distinct_id` String, `dual_channel` String, `duration` String, `email` String, `email_domain` String, `_kx` String, `dclid` String, `epik` String, `entity_detection` String, `env` String, `environment` String, `event` String, `event_count_in_month` String, `event_count_in_period` String, `events_projected_amount` String, `fbclid` String, `filter_profanity` String, `filters_count` String, `function` String, `gad_source` String, `gbraid` String, `gclid` String, `gclsrc` String, `gross` String, `group_id` String, `historical_migration` String, `iab_categories` String, `id` String, `index` String, `initial_dclid` String, `initial_fbclid` String, `initial_gclsrc` String, `initial__kx` String, `initial_epik` String, `initial_gad_source` String, `initial_gbraid` String, `initial_gclid` String, `initial_irclid` String, `initial_igshid` String, `initial_li_fat_id` String, `initial_mc_cid` String, `initial_msclkid` String, `initial_qclid` String, `initial_rdt_cid` String, `initial_sccid` String, `initial_utm_campaign` String, `initial_utm_content` String, `initial_utm_medium` String, `initial_utm_source` String, `initial_utm_term` String, `initial_step` String, `initial_ttclid` String, `initial_twclid` String, `initial_wbraid` String, `initiator` String, `insight` String, `institution_name` String, `inviteCode` String, `is_demo_project` String, `is_first_component_load` String, `is_first_event_for_user` String, `is_initial_aggregation` String, `is_oauth` String, `is_organization_first_user` String, `is_test_user` String, `item_count` String, `job_type` String, `key` String, `kind` String, `language_detection` String, `machine_id` String, `message` String, `method` String, `mode` String, `most_recent_app_os` String, `msclkid` String, `mc_cid` String, `igshid` String, `irclid` String, `li_fat_id` String, `qclid` String, `rdt_cid` String, `sccid` String, `ttclid` String, `twclid` String, `name` String, `nativeBuildVersion` String, `numberOfSecrets` String, `orderId` String, `orderType` String, `organization` String, `organization_id` String, `organization_name` String, `organizations` String, `origin` String, `osName` String, `owner_type` String, `page` String, `payment_status` String, `phone` String, `platform` String, `product` String, `product_analytics_projected_amount` String, `product_key` String, `progress` String, `protocol` String, `query` String, `ramp` String, `realm` String, `record-id` String, `recording_count_in_period` String, `recordings_projected_amount` String, `redact_pii` String, `referrer` String, `referrer_id` String, `region` String, `revenue` String, `screen_name` String, `sdk` String, `search_term` String, `sentiment_analysis` String, `session_replay_projected_amount` String, `sku` String, `source` String, `speaker_labels` String, `statusCode` String, `status_message` String, `store_url` String, `stripe_amount_paid` String, `subdomain` String, `subscriptionStatus` String, `summarization` String, `surface_tag` String, `survey_responses_count_in_period` String, `symbol` String, `tag` String, `target` String, `team` String, `testSessionId` String, `thread_id` String, `ticketId` String, `title` String, `token` String, `total_event_actions_count` String, `total_usd` String, `type` String, `url` String, `url_promotion_id` String, `usd` String, `user_agent` String, `user_email_domain` String, `user_platform` String, `utm_campaign` String, `utm_content` String, `utm_medium` String, `utm_source` String, `utm_term` String, `valid_ach_accounts` String, `wbraid` String, `wlo_enabled` String, `workplace_billing_plan` String, `workspace` String, `workspaceId` String)"
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
    column "elements_hash" {
      type = "String"
    }
    column "created_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "elements_chain" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    column "person_properties" {
      type = "JSON(max_dynamic_paths=0, `$app_version` String, `$app_build` String, `$app_name` String, `$app_namespace` String, `$browser` String, `$browser_language` String, `$browser_language_prefix` String, `$browser_type` String, `$browser_version` String, `$current_url` String, `$device` String, `$device_id` String, `$device_manufacturer` String, `$device_model` String, `$device_name` String, `$device_type` String, `$geoip_continent_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_city_name` LowCardinality(String), `$geoip_postal_code` String, `$geoip_subdivision_1_code` String, `$geoip_subdivision_1_name` String, `$geoip_subdivision_2_code` String, `$geoip_subdivision_2_name` String, `$geoip_time_zone` LowCardinality(String), `$initial_current_url` String, `$initial_app_build` String, `$initial_app_name` String, `$initial_app_namespace` String, `$initial_app_version` String, `$initial_browser` String, `$initial_browser_language` String, `$initial_browser_language_prefix` String, `$initial_browser_type` String, `$initial_browser_version` String, `$initial_device` String, `$initial_device_id` String, `$initial_device_manufacturer` String, `$initial_device_model` String, `$initial_device_name` String, `$initial_device_type` String, `$initial_geoip_city_name` String, `$initial_geoip_continent_code` String, `$initial_geoip_continent_name` String, `$initial_geoip_country_code` String, `$initial_geoip_country_name` String, `$initial_geoip_postal_code` String, `$initial_geoip_subdivision_1_code` String, `$initial_geoip_subdivision_1_name` String, `$initial_geoip_subdivision_2_code` String, `$initial_geoip_subdivision_2_name` String, `$initial_geoip_time_zone` String, `$initial_fbclid` String, `$initial_gad_source` String, `$initial_gbraid` String, `$initial_gclid` String, `$initial_gclsrc` String, `$initial_dclid` String, `$initial_msclkid` String, `$initial_twclid` String, `$initial_li_fat_id` String, `$initial_mc_cid` String, `$initial_igshid` String, `$initial_ttclid` String, `$initial_rdt_cid` String, `$initial_epik` String, `$initial_qclid` String, `$initial_sccid` String, `$initial_irclid` String, `$initial__kx` String, `$initial_pathname` String, `$initial_os` String, `$initial_os_name` String, `$initial_os_version` String, `$initial_raw_user_agent` String, `$initial_referrer` String, `$initial_referring_domain` String, `$initial_screen_height` String, `$initial_screen_width` String, `$initial_search_engine` String, `$initial_utm_campaign` String, `$initial_utm_content` String, `$initial_utm_medium` String, `$initial_utm_source` String, `$initial_utm_term` String, `$initial_viewport_height` String, `$initial_viewport_width` String, `$initial_wbraid` String, `$os_name` String, `$os` String, `$os_version` String, `$pathname` String, `$raw_user_agent` String, `$referrer` String, `$screen_height` String, `$screen_width` String, `$search_engine` String, `$viewport_height` String, `$viewport_width` String, `$referring_domain` String, `$email` String, `$last_seen_survey_date` String, `$organization_id` String, `$product_tour_last_seen_date` String, `$survey_last_seen_date` String, `Email Domain` String, `companyName` String, `customer` String, `email` String, `first_name` String, `hubspot_score` String, `id` String, `icp_role` String, `is_email_verified` String, `is_signed_up` String, `last_name` String, `name` String, `organization_id` String, `organization_member_count` String, `role` String, `role_at_organization` String, `serverMarketing` String, `serverMasterclass` String, `user_email_domain` String, `username` String, `utm_source` String, `utm_medium` String, `utm_campaign` String, `utm_content` String, `utm_term` String, `gclid` String, `gad_source` String, `gclsrc` String, `dclid` String, `gbraid` String, `wbraid` String, `fbclid` String, `msclkid` String, `twclid` String, `li_fat_id` String, `mc_cid` String, `igshid` String, `ttclid` String, `rdt_cid` String, `epik` String, `qclid` String, `sccid` String, `irclid` String, `_kx` String, `val_region` String)"
    }
    column "_unparseable_properties" {
      type = "String"
    }
    column "_unparseable_person_properties" {
      type = "String"
    }
    column "_active_feature_flags" {
      type = "String"
    }
    column "group0_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group1_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group2_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group3_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "group4_properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "person_created_at" {
      type = "DateTime64(3)"
    }
    column "group0_created_at" {
      type = "DateTime64(3)"
    }
    column "group1_created_at" {
      type = "DateTime64(3)"
    }
    column "group2_created_at" {
      type = "DateTime64(3)"
    }
    column "group3_created_at" {
      type = "DateTime64(3)"
    }
    column "group4_created_at" {
      type = "DateTime64(3)"
    }
    column "inserted_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
    column "historical_migration" {
      type = "Bool"
    }
    column "total_event_size" {
      type = "UInt32"
    }
    column "captured_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "_partition" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_events_json"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }

  table "writable_logs34" {
    settings = {
      background_insert_batch = "1"
    }
    column "time_bucket" {
      type         = "DateTime"
      materialized = "toStartOfDay(timestamp)"
    }
    column "original_expiry_timestamp" {
      type = "DateTime64(6)"
    }
    column "uuid" {
      type = "String"
    }
    column "team_id" {
      type = "Int32"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "trace_flags" {
      type = "Int32"
    }
    column "timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "created_at" {
      type         = "DateTime64(6)"
      materialized = "now()"
    }
    column "body" {
      type = "String"
    }
    column "severity_text" {
      type = "LowCardinality(String)"
    }
    column "severity_number" {
      type = "Int32"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "resource_fingerprint" {
      type         = "UInt64"
      materialized = "cityHash64(resource_attributes)"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "event_name" {
      type = "String"
    }
    column "attributes_map_str" {
      type = "Map(LowCardinality(String), String)"
    }
    column "level" {
      type  = "String"
      alias = "severity_text"
    }
    column "mat_body_ipv4_matches" {
      type  = "Array(String)"
      alias = "extractAll(body, '(\\\\d\\\\.((25[0-5]|(2[0-4]|1(0, 1)[0-9])(0, 1)[0-9])\\\\.)(2, 2)([0-9]))')"
    }
    column "time_minute" {
      type  = "DateTime"
      alias = "toStartOfMinute(timestamp)"
    }
    column "attributes" {
      type  = "Map(LowCardinality(String), String)"
      alias = "mapApply((k, v) -> (left(k, -5), v), attributes_map_str)"
    }
    column "attributes_map_float" {
      type         = "Map(LowCardinality(String), Float64)"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str))"
    }
    column "attributes_map_datetime" {
      type         = "Map(LowCardinality(String), DateTime64(6))"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str))"
    }
    column "_partition" {
      type = "UInt32"
    }
    column "_topic" {
      type = "String"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_bytes_uncompressed" {
      type = "UInt64"
    }
    column "_bytes_compressed" {
      type = "UInt64"
    }
    column "_record_count" {
      type = "UInt64"
    }
    column "pattern" {
      type = "String"
    }
    column "pattern_version" {
      type = "UInt8"
    }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "logs34"
    }
  }

  materialized_view "events_json_table_mv" {
    to_table = "posthog.writable_events_json"
    query    = <<SQL
WITH
  if(isValidJSON(source.properties) AND startsWith(trimLeft(source.properties), '{'), JSONCleanPostHogEventProperties(source.properties), concat('{"$unparseable_properties":', toJSONString(source.properties), '}')) AS cleaned_properties,
  if(isValidJSON(source.person_properties) AND startsWith(trimLeft(source.person_properties), '{'), JSONCleanPostHogPersonProperties(source.person_properties), concat('{"$unparseable_properties":', toJSONString(source.person_properties), '}')) AS cleaned_person_properties,
  if(JSONType(source.properties, '$active_feature_flags') = 'Array', JSONExtractRaw(source.properties, '$active_feature_flags'), '') AS _active_feature_flags,
  JSONDropKeys(['$unparseable_properties'])(cleaned_properties) AS visible_properties,
  JSONDropKeys(['$unparseable_properties'])(cleaned_person_properties) AS visible_person_properties,
  accurateCastOrNull(visible_properties, 'JSON(max_dynamic_paths = 0, `$agent_application_id` String, `$agent_revision_id` String, `$agent_session_id` String, `$agent_turn` String, `$ai_audio_cost_usd` String, `$ai_audio_input_tokens` String, `$ai_audio_output_tokens` String, `$ai_batch_run_id` String, `$ai_cache_creation_input_tokens` String, `$ai_cache_read_input_tokens` String, `$ai_error` String, `$ai_error_normalized` String, `$ai_error_type` String, `$ai_evaluation_allows_na` String, `$ai_evaluation_applicable` String, `$ai_evaluation_id` String, `$ai_evaluation_name` String, `$ai_evaluation_reasoning` String, `$ai_evaluation_result` String, `$ai_evaluation_result_type` String, `$ai_evaluation_runtime` String, `$ai_evaluation_skipped` String, `$ai_evaluation_start_time` String, `$ai_evaluation_type` String, `$ai_experiment_id` String, `$ai_framework` String, `$ai_generation_id` String, `$ai_http_status` String, `$ai_image_cost_usd` String, `$ai_image_input_tokens` String, `$ai_image_output_tokens` String, `$ai_input_cost_usd` String, `$ai_input_tokens` String, `$ai_is_error` String, `$ai_latency` String, `$ai_model` String, `$ai_output_cost_usd` String, `$ai_output_tokens` String, `$ai_parent_id` String, `$ai_prompt_name` String, `$ai_provider` String, `$ai_reasoning_tokens` String, `$ai_request_cost_usd` String, `$ai_session_id` String, `$ai_span_name` String, `$ai_span_type` String, `$ai_span_id` String, `$ai_sentiment_label` String, `$ai_sentiment_message_count` String, `$ai_sentiment_score` String, `$ai_target_event_id` String, `$ai_text_input_tokens` String, `$ai_text_output_tokens` String, `$ai_time_to_first_token` String, `$ai_total_cost_usd` String, `$ai_total_tokens` String, `$ai_tools_called` String, `$ai_trace_id` String, `$ai_trace_name` String, `$ai_video_cost_usd` String, `$ai_video_input_tokens` String, `$ai_video_output_tokens` String, `$ai_web_search_cost_usd` String, `$ai_web_search_count` String, `$ai_origin` String, `$anon_distinct_id` String, `$app_build` String, `$app_name` String, `$app_namespace` String, `$app_version` String, `$browser` String, `$browser_language` String, `$browser_language_prefix` String, `$browser_type` String, `$browser_version` String, `$current_url` String, `$device` String, `$device_id` String, `$device_model` String, `$device_manufacturer` String, `$device_name` String, `$device_type` String, `$el_text` String, `$event_type` String, `$exception_fingerprint` String, `$exception_functions` Array(String), `$exception_handled` String, `$exception_is_synthetic` String, `$exception_issue_id` String, `$exception_level` String, `$exception_list` Array(JSON(max_dynamic_paths = 0, type String, value String)), `$exception_message` String, `$exception_proposed_fingerprint` String, `$exception_sources` Array(String), `$exception_type` String, `$exception_types` Array(String), `$exception_values` Array(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_postal_code` String, `$geoip_subdivision_1_name` String, `$geoip_subdivision_2_code` String, `$geoip_subdivision_2_name` String, `$geoip_time_zone` LowCardinality(String), `$geoip_subdivision_1_code` String, `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$groups.organization` String, `$groups.project` String, `$groups.instance` String, `$group_set.icp_company_type` String, `$host` String, `$initial_pathname` String, `$initial_referrer` String, `$initial_referring_domain` String, `$client_session_initial_pathname` String, `$client_session_initial_referring_host` String, `$client_session_initial_utm_campaign` String, `$client_session_initial_utm_content` String, `$client_session_initial_utm_medium` String, `$client_session_initial_utm_source` String, `$client_session_initial_utm_term` String, `$initial_search_engine` String, `$ip` String, `$is_identified` String, `$lib` String, `$lib_custom_api_host` String, `$lib_version` String, `$lib_version__minor` String, `$mcp_client_name` String, `$mcp_client_user_agent` String, `$mcp_duration_ms` String, `$mcp_error_message` String, `$mcp_exec_tool_call_description` String, `$mcp_exec_tool_call_name` String, `$mcp_intent` String, `$mcp_intent_source` String, `$mcp_is_error` String, `$mcp_listed_tool_names` Array(String), `$mcp_oauth_client_name` String, `$mcp_organization_id` String, `$mcp_project_id` String, `$mcp_session_id` String, `$mcp_source` String, `$mcp_tool_category` String, `$mcp_tool_description` String, `$mcp_tool_name` String, `$os` String, `$os_name` String, `$os_version` String, `$pathname` String, `$prev_pageview_max_content_percentage` String, `$prev_pageview_max_scroll_percentage` String, `$prev_pageview_pathname` String, `$process_person_profile` String, `$recording_status` String, `$referrer` String, `$referring_domain` String, `$replay_minimum_duration` String, `$replay_sample_rate` String, `$raw_user_agent` String, `$search_engine` String, `$screen_height` String, `$screen_name` String, `$screen_width` String, `$sent_at` String, `$session_id` String, `$session_entry_host` String, `$session_entry_pathname` String, `$session_entry_referrer` String, `$session_entry_referring_domain` String, `$session_entry_search_engine` String, `$session_entry_url` String, `$session_entry_utm_campaign` String, `$session_entry_utm_content` String, `$session_entry_utm_medium` String, `$session_entry_utm_source` String, `$session_entry_utm_term` String, `$session_recording_event_trigger_activated_session` String, `$session_recording_start_reason` String, `$session_recording_url_trigger_status` String, `$sdk_debug_recording_script_not_loaded` String, `$survey_id` String, `$survey_completed` String, `$survey_iteration` String, `$survey_iteration_start_date` String, `$survey_name` String, `$survey_partially_completed` String, `$survey_response` String, `$survey_response_1` String, `$survey_submission_id` String, `$time` String, `$timezone` String, `$timezone_offset` String, `$user_id` String, `$viewport_height` String, `$viewport_width` String, `$web_vitals_CLS_value` String, `$web_vitals_FCP_value` String, `$web_vitals_INP_value` String, `$web_vitals_LCP_value` String, `$window_id` String, `Account.client_id` String, `Connection.app.name` String, `Event.productCode` String, `HTTP Method` String, `Plan type and filter` String, `Subscription.plan.amount` String, action String, action_name String, address String, apiErrorMessage String, apiName String, app_name String, app_version String, arguments String, audio_duration String, authentication_method String, auto_chapters String, auto_highlights String, category String, chain String, channel String, client_id String, client_name String, commit_sha String, community_id String, conceptName String, content_length String, content_safety String, context String, contributionError String, created_at String, created_by String, created_by_system String, currentScreen String, current_member_guid String, customer_email String, deal_id String, device_type String, disable_institution_search String, disfluencies String, distinct_id String, dual_channel String, duration String, email String, email_domain String, _kx String, dclid String, epik String, entity_detection String, env String, environment String, event String, event_count_in_month String, event_count_in_period String, events_projected_amount String, fbclid String, filter_profanity String, filters_count String, function String, gad_source String, gbraid String, gclid String, gclsrc String, gross String, group_id String, historical_migration String, iab_categories String, id String, index String, initial_dclid String, initial_fbclid String, initial_gclsrc String, initial__kx String, initial_epik String, initial_gad_source String, initial_gbraid String, initial_gclid String, initial_irclid String, initial_igshid String, initial_li_fat_id String, initial_mc_cid String, initial_msclkid String, initial_qclid String, initial_rdt_cid String, initial_sccid String, initial_utm_campaign String, initial_utm_content String, initial_utm_medium String, initial_utm_source String, initial_utm_term String, initial_step String, initial_ttclid String, initial_twclid String, initial_wbraid String, initiator String, insight String, institution_name String, inviteCode String, is_demo_project String, is_first_component_load String, is_first_event_for_user String, is_initial_aggregation String, is_oauth String, is_organization_first_user String, is_test_user String, item_count String, job_type String, key String, kind String, language_detection String, machine_id String, message String, method String, mode String, most_recent_app_os String, msclkid String, mc_cid String, igshid String, irclid String, li_fat_id String, qclid String, rdt_cid String, sccid String, ttclid String, twclid String, name String, nativeBuildVersion String, numberOfSecrets String, orderId String, orderType String, organization String, organization_id String, organization_name String, organizations String, origin String, osName String, owner_type String, page String, payment_status String, phone String, platform String, product String, product_analytics_projected_amount String, product_key String, progress String, protocol String, query String, ramp String, realm String, `record-id` String, recording_count_in_period String, recordings_projected_amount String, redact_pii String, referrer String, referrer_id String, region String, revenue String, screen_name String, sdk String, search_term String, sentiment_analysis String, session_replay_projected_amount String, sku String, source String, speaker_labels String, statusCode String, status_message String, store_url String, stripe_amount_paid String, subdomain String, subscriptionStatus String, summarization String, surface_tag String, survey_responses_count_in_period String, symbol String, tag String, target String, team String, testSessionId String, thread_id String, ticketId String, title String, token String, total_event_actions_count String, total_usd String, type String, url String, url_promotion_id String, usd String, user_agent String, user_email_domain String, user_platform String, utm_campaign String, utm_content String, utm_medium String, utm_source String, utm_term String, valid_ach_accounts String, wbraid String, wlo_enabled String, workplace_billing_plan String, workspace String, workspaceId String)') AS typed_properties,
  accurateCastOrNull(visible_person_properties, 'JSON(max_dynamic_paths = 0, `$app_version` String, `$app_build` String, `$app_name` String, `$app_namespace` String, `$browser` String, `$browser_language` String, `$browser_language_prefix` String, `$browser_type` String, `$browser_version` String, `$current_url` String, `$device` String, `$device_id` String, `$device_manufacturer` String, `$device_model` String, `$device_name` String, `$device_type` String, `$geoip_continent_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_city_name` LowCardinality(String), `$geoip_postal_code` String, `$geoip_subdivision_1_code` String, `$geoip_subdivision_1_name` String, `$geoip_subdivision_2_code` String, `$geoip_subdivision_2_name` String, `$geoip_time_zone` LowCardinality(String), `$initial_current_url` String, `$initial_app_build` String, `$initial_app_name` String, `$initial_app_namespace` String, `$initial_app_version` String, `$initial_browser` String, `$initial_browser_language` String, `$initial_browser_language_prefix` String, `$initial_browser_type` String, `$initial_browser_version` String, `$initial_device` String, `$initial_device_id` String, `$initial_device_manufacturer` String, `$initial_device_model` String, `$initial_device_name` String, `$initial_device_type` String, `$initial_geoip_city_name` String, `$initial_geoip_continent_code` String, `$initial_geoip_continent_name` String, `$initial_geoip_country_code` String, `$initial_geoip_country_name` String, `$initial_geoip_postal_code` String, `$initial_geoip_subdivision_1_code` String, `$initial_geoip_subdivision_1_name` String, `$initial_geoip_subdivision_2_code` String, `$initial_geoip_subdivision_2_name` String, `$initial_geoip_time_zone` String, `$initial_fbclid` String, `$initial_gad_source` String, `$initial_gbraid` String, `$initial_gclid` String, `$initial_gclsrc` String, `$initial_dclid` String, `$initial_msclkid` String, `$initial_twclid` String, `$initial_li_fat_id` String, `$initial_mc_cid` String, `$initial_igshid` String, `$initial_ttclid` String, `$initial_rdt_cid` String, `$initial_epik` String, `$initial_qclid` String, `$initial_sccid` String, `$initial_irclid` String, `$initial__kx` String, `$initial_pathname` String, `$initial_os` String, `$initial_os_name` String, `$initial_os_version` String, `$initial_raw_user_agent` String, `$initial_referrer` String, `$initial_referring_domain` String, `$initial_screen_height` String, `$initial_screen_width` String, `$initial_search_engine` String, `$initial_utm_campaign` String, `$initial_utm_content` String, `$initial_utm_medium` String, `$initial_utm_source` String, `$initial_utm_term` String, `$initial_viewport_height` String, `$initial_viewport_width` String, `$initial_wbraid` String, `$os_name` String, `$os` String, `$os_version` String, `$pathname` String, `$raw_user_agent` String, `$referrer` String, `$screen_height` String, `$screen_width` String, `$search_engine` String, `$viewport_height` String, `$viewport_width` String, `$referring_domain` String, `$email` String, `$last_seen_survey_date` String, `$organization_id` String, `$product_tour_last_seen_date` String, `$survey_last_seen_date` String, `Email Domain` String, companyName String, customer String, email String, first_name String, hubspot_score String, id String, icp_role String, is_email_verified String, is_signed_up String, last_name String, name String, organization_id String, organization_member_count String, role String, role_at_organization String, serverMarketing String, serverMasterclass String, user_email_domain String, username String, utm_source String, utm_medium String, utm_campaign String, utm_content String, utm_term String, gclid String, gad_source String, gclsrc String, dclid String, gbraid String, wbraid String, fbclid String, msclkid String, twclid String, li_fat_id String, mc_cid String, igshid String, ttclid String, rdt_cid String, epik String, qclid String, sccid String, irclid String, _kx String, val_region String)') AS typed_person_properties
SELECT
  *,
  accurateCast(byteSize(*) + byteSize(toUInt32(0)), 'UInt32') AS total_event_size
FROM
  (
    SELECT
      uuid,
      event,
      ifNull(typed_properties, defaultValueOfArgumentType(assumeNotNull(typed_properties))) AS properties,
      timestamp,
      team_id,
      distinct_id,
      elements_chain,
      created_at,
      person_id,
      ifNull(
        typed_person_properties,
        defaultValueOfArgumentType(assumeNotNull(typed_person_properties))
      ) AS person_properties,
      if(
        isNull(typed_properties),
        source.properties,
        JSONExtractString(cleaned_properties, '$unparseable_properties')
      ) AS _unparseable_properties,
      if(
        isNull(typed_person_properties),
        source.person_properties,
        JSONExtractString(cleaned_person_properties, '$unparseable_properties')
      ) AS _unparseable_person_properties,
      _active_feature_flags,
      person_created_at,
      group0_properties,
      group1_properties,
      group2_properties,
      group3_properties,
      group4_properties,
      group0_created_at,
      group1_created_at,
      group2_created_at,
      group3_created_at,
      group4_created_at,
      person_mode,
      historical_migration,
      coalesce(captured_at, created_at) AS captured_at,
      _timestamp,
      _offset,
      _partition,
      arrayMap(
        i -> (_headers.value[i]),
        arrayFilter(
          i -> ((_headers.name[i]) = 'kafka-consumer-breadcrumbs'),
          arrayEnumerate(_headers.name)
        )
      ) AS consumer_breadcrumbs
    FROM posthog.kafka_events_json_native_json AS source
  )
SQL

    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "JSON(max_dynamic_paths=0, `$agent_application_id` String, `$agent_revision_id` String, `$agent_session_id` String, `$agent_turn` String, `$ai_audio_cost_usd` String, `$ai_audio_input_tokens` String, `$ai_audio_output_tokens` String, `$ai_batch_run_id` String, `$ai_cache_creation_input_tokens` String, `$ai_cache_read_input_tokens` String, `$ai_error` String, `$ai_error_normalized` String, `$ai_error_type` String, `$ai_evaluation_allows_na` String, `$ai_evaluation_applicable` String, `$ai_evaluation_id` String, `$ai_evaluation_name` String, `$ai_evaluation_reasoning` String, `$ai_evaluation_result` String, `$ai_evaluation_result_type` String, `$ai_evaluation_runtime` String, `$ai_evaluation_skipped` String, `$ai_evaluation_start_time` String, `$ai_evaluation_type` String, `$ai_experiment_id` String, `$ai_framework` String, `$ai_generation_id` String, `$ai_http_status` String, `$ai_image_cost_usd` String, `$ai_image_input_tokens` String, `$ai_image_output_tokens` String, `$ai_input_cost_usd` String, `$ai_input_tokens` String, `$ai_is_error` String, `$ai_latency` String, `$ai_model` String, `$ai_origin` String, `$ai_output_cost_usd` String, `$ai_output_tokens` String, `$ai_parent_id` String, `$ai_prompt_name` String, `$ai_provider` String, `$ai_reasoning_tokens` String, `$ai_request_cost_usd` String, `$ai_sentiment_label` String, `$ai_sentiment_message_count` String, `$ai_sentiment_score` String, `$ai_session_id` String, `$ai_span_id` String, `$ai_span_name` String, `$ai_span_type` String, `$ai_target_event_id` String, `$ai_text_input_tokens` String, `$ai_text_output_tokens` String, `$ai_time_to_first_token` String, `$ai_tools_called` String, `$ai_total_cost_usd` String, `$ai_total_tokens` String, `$ai_trace_id` String, `$ai_trace_name` String, `$ai_video_cost_usd` String, `$ai_video_input_tokens` String, `$ai_video_output_tokens` String, `$ai_web_search_cost_usd` String, `$ai_web_search_count` String, `$anon_distinct_id` String, `$app_build` String, `$app_name` String, `$app_namespace` String, `$app_version` String, `$browser` String, `$browser_language` String, `$browser_language_prefix` String, `$browser_type` String, `$browser_version` String, `$client_session_initial_pathname` String, `$client_session_initial_referring_host` String, `$client_session_initial_utm_campaign` String, `$client_session_initial_utm_content` String, `$client_session_initial_utm_medium` String, `$client_session_initial_utm_source` String, `$client_session_initial_utm_term` String, `$current_url` String, `$device` String, `$device_id` String, `$device_manufacturer` String, `$device_model` String, `$device_name` String, `$device_type` String, `$el_text` String, `$event_type` String, `$exception_fingerprint` String, `$exception_functions` Array(String), `$exception_handled` String, `$exception_is_synthetic` String, `$exception_issue_id` String, `$exception_level` String, `$exception_list` Array(JSON(max_dynamic_paths=0, type String, value String)), `$exception_message` String, `$exception_proposed_fingerprint` String, `$exception_sources` Array(String), `$exception_type` String, `$exception_types` Array(String), `$exception_values` Array(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_postal_code` String, `$geoip_subdivision_1_code` String, `$geoip_subdivision_1_name` String, `$geoip_subdivision_2_code` String, `$geoip_subdivision_2_name` String, `$geoip_time_zone` LowCardinality(String), `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$group_set.icp_company_type` String, `$groups.instance` String, `$groups.organization` String, `$groups.project` String, `$host` String, `$initial_pathname` String, `$initial_referrer` String, `$initial_referring_domain` String, `$initial_search_engine` String, `$ip` String, `$is_identified` String, `$lib` String, `$lib_custom_api_host` String, `$lib_version` String, `$lib_version__minor` String, `$mcp_client_name` String, `$mcp_client_user_agent` String, `$mcp_duration_ms` String, `$mcp_error_message` String, `$mcp_exec_tool_call_description` String, `$mcp_exec_tool_call_name` String, `$mcp_intent` String, `$mcp_intent_source` String, `$mcp_is_error` String, `$mcp_listed_tool_names` Array(String), `$mcp_oauth_client_name` String, `$mcp_organization_id` String, `$mcp_project_id` String, `$mcp_session_id` String, `$mcp_source` String, `$mcp_tool_category` String, `$mcp_tool_description` String, `$mcp_tool_name` String, `$os` String, `$os_name` String, `$os_version` String, `$pathname` String, `$prev_pageview_max_content_percentage` String, `$prev_pageview_max_scroll_percentage` String, `$prev_pageview_pathname` String, `$process_person_profile` String, `$raw_user_agent` String, `$recording_status` String, `$referrer` String, `$referring_domain` String, `$replay_minimum_duration` String, `$replay_sample_rate` String, `$screen_height` String, `$screen_name` String, `$screen_width` String, `$sdk_debug_recording_script_not_loaded` String, `$search_engine` String, `$sent_at` String, `$session_entry_host` String, `$session_entry_pathname` String, `$session_entry_referrer` String, `$session_entry_referring_domain` String, `$session_entry_search_engine` String, `$session_entry_url` String, `$session_entry_utm_campaign` String, `$session_entry_utm_content` String, `$session_entry_utm_medium` String, `$session_entry_utm_source` String, `$session_entry_utm_term` String, `$session_id` String, `$session_recording_event_trigger_activated_session` String, `$session_recording_start_reason` String, `$session_recording_url_trigger_status` String, `$survey_completed` String, `$survey_id` String, `$survey_iteration` String, `$survey_iteration_start_date` String, `$survey_name` String, `$survey_partially_completed` String, `$survey_response` String, `$survey_response_1` String, `$survey_submission_id` String, `$time` String, `$timezone` String, `$timezone_offset` String, `$user_id` String, `$viewport_height` String, `$viewport_width` String, `$web_vitals_CLS_value` String, `$web_vitals_FCP_value` String, `$web_vitals_INP_value` String, `$web_vitals_LCP_value` String, `$window_id` String, `Account.client_id` String, `Connection.app.name` String, `Event.productCode` String, `HTTP Method` String, `Plan type and filter` String, `Subscription.plan.amount` String, _kx String, action String, action_name String, address String, apiErrorMessage String, apiName String, app_name String, app_version String, arguments String, audio_duration String, authentication_method String, auto_chapters String, auto_highlights String, category String, chain String, channel String, client_id String, client_name String, commit_sha String, community_id String, conceptName String, content_length String, content_safety String, context String, contributionError String, created_at String, created_by String, created_by_system String, currentScreen String, current_member_guid String, customer_email String, dclid String, deal_id String, device_type String, disable_institution_search String, disfluencies String, distinct_id String, dual_channel String, duration String, email String, email_domain String, entity_detection String, env String, environment String, epik String, event String, event_count_in_month String, event_count_in_period String, events_projected_amount String, fbclid String, filter_profanity String, filters_count String, function String, gad_source String, gbraid String, gclid String, gclsrc String, gross String, group_id String, historical_migration String, iab_categories String, id String, igshid String, index String, initial__kx String, initial_dclid String, initial_epik String, initial_fbclid String, initial_gad_source String, initial_gbraid String, initial_gclid String, initial_gclsrc String, initial_igshid String, initial_irclid String, initial_li_fat_id String, initial_mc_cid String, initial_msclkid String, initial_qclid String, initial_rdt_cid String, initial_sccid String, initial_step String, initial_ttclid String, initial_twclid String, initial_utm_campaign String, initial_utm_content String, initial_utm_medium String, initial_utm_source String, initial_utm_term String, initial_wbraid String, initiator String, insight String, institution_name String, inviteCode String, irclid String, is_demo_project String, is_first_component_load String, is_first_event_for_user String, is_initial_aggregation String, is_oauth String, is_organization_first_user String, is_test_user String, item_count String, job_type String, key String, kind String, language_detection String, li_fat_id String, machine_id String, mc_cid String, message String, method String, mode String, most_recent_app_os String, msclkid String, name String, nativeBuildVersion String, numberOfSecrets String, orderId String, orderType String, organization String, organization_id String, organization_name String, organizations String, origin String, osName String, owner_type String, page String, payment_status String, phone String, platform String, product String, product_analytics_projected_amount String, product_key String, progress String, protocol String, qclid String, query String, ramp String, rdt_cid String, realm String, `record-id` String, recording_count_in_period String, recordings_projected_amount String, redact_pii String, referrer String, referrer_id String, region String, revenue String, sccid String, screen_name String, sdk String, search_term String, sentiment_analysis String, session_replay_projected_amount String, sku String, source String, speaker_labels String, statusCode String, status_message String, store_url String, stripe_amount_paid String, subdomain String, subscriptionStatus String, summarization String, surface_tag String, survey_responses_count_in_period String, symbol String, tag String, target String, team String, testSessionId String, thread_id String, ticketId String, title String, token String, total_event_actions_count String, total_usd String, ttclid String, twclid String, type String, url String, url_promotion_id String, usd String, user_agent String, user_email_domain String, user_platform String, utm_campaign String, utm_content String, utm_medium String, utm_source String, utm_term String, valid_ach_accounts String, wbraid String, wlo_enabled String, workplace_billing_plan String, workspace String, workspaceId String)"
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
      type = "JSON(max_dynamic_paths=0, `$app_build` String, `$app_name` String, `$app_namespace` String, `$app_version` String, `$browser` String, `$browser_language` String, `$browser_language_prefix` String, `$browser_type` String, `$browser_version` String, `$current_url` String, `$device` String, `$device_id` String, `$device_manufacturer` String, `$device_model` String, `$device_name` String, `$device_type` String, `$email` String, `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_postal_code` String, `$geoip_subdivision_1_code` String, `$geoip_subdivision_1_name` String, `$geoip_subdivision_2_code` String, `$geoip_subdivision_2_name` String, `$geoip_time_zone` LowCardinality(String), `$initial__kx` String, `$initial_app_build` String, `$initial_app_name` String, `$initial_app_namespace` String, `$initial_app_version` String, `$initial_browser` String, `$initial_browser_language` String, `$initial_browser_language_prefix` String, `$initial_browser_type` String, `$initial_browser_version` String, `$initial_current_url` String, `$initial_dclid` String, `$initial_device` String, `$initial_device_id` String, `$initial_device_manufacturer` String, `$initial_device_model` String, `$initial_device_name` String, `$initial_device_type` String, `$initial_epik` String, `$initial_fbclid` String, `$initial_gad_source` String, `$initial_gbraid` String, `$initial_gclid` String, `$initial_gclsrc` String, `$initial_geoip_city_name` String, `$initial_geoip_continent_code` String, `$initial_geoip_continent_name` String, `$initial_geoip_country_code` String, `$initial_geoip_country_name` String, `$initial_geoip_postal_code` String, `$initial_geoip_subdivision_1_code` String, `$initial_geoip_subdivision_1_name` String, `$initial_geoip_subdivision_2_code` String, `$initial_geoip_subdivision_2_name` String, `$initial_geoip_time_zone` String, `$initial_igshid` String, `$initial_irclid` String, `$initial_li_fat_id` String, `$initial_mc_cid` String, `$initial_msclkid` String, `$initial_os` String, `$initial_os_name` String, `$initial_os_version` String, `$initial_pathname` String, `$initial_qclid` String, `$initial_raw_user_agent` String, `$initial_rdt_cid` String, `$initial_referrer` String, `$initial_referring_domain` String, `$initial_sccid` String, `$initial_screen_height` String, `$initial_screen_width` String, `$initial_search_engine` String, `$initial_ttclid` String, `$initial_twclid` String, `$initial_utm_campaign` String, `$initial_utm_content` String, `$initial_utm_medium` String, `$initial_utm_source` String, `$initial_utm_term` String, `$initial_viewport_height` String, `$initial_viewport_width` String, `$initial_wbraid` String, `$last_seen_survey_date` String, `$organization_id` String, `$os` String, `$os_name` String, `$os_version` String, `$pathname` String, `$product_tour_last_seen_date` String, `$raw_user_agent` String, `$referrer` String, `$referring_domain` String, `$screen_height` String, `$screen_width` String, `$search_engine` String, `$survey_last_seen_date` String, `$viewport_height` String, `$viewport_width` String, `Email Domain` String, _kx String, companyName String, customer String, dclid String, email String, epik String, fbclid String, first_name String, gad_source String, gbraid String, gclid String, gclsrc String, hubspot_score String, icp_role String, id String, igshid String, irclid String, is_email_verified String, is_signed_up String, last_name String, li_fat_id String, mc_cid String, msclkid String, name String, organization_id String, organization_member_count String, qclid String, rdt_cid String, role String, role_at_organization String, sccid String, serverMarketing String, serverMasterclass String, ttclid String, twclid String, user_email_domain String, username String, utm_campaign String, utm_content String, utm_medium String, utm_source String, utm_term String, val_region String, wbraid String)"
    }
    column "_unparseable_properties" {
      type = "String"
    }
    column "_unparseable_person_properties" {
      type = "String"
    }
    column "_active_feature_flags" {
      type = "String"
    }
    column "person_created_at" {
      type = "DateTime64(3)"
    }
    column "group0_properties" {
      type = "String"
    }
    column "group1_properties" {
      type = "String"
    }
    column "group2_properties" {
      type = "String"
    }
    column "group3_properties" {
      type = "String"
    }
    column "group4_properties" {
      type = "String"
    }
    column "group0_created_at" {
      type = "DateTime64(3)"
    }
    column "group1_created_at" {
      type = "DateTime64(3)"
    }
    column "group2_created_at" {
      type = "DateTime64(3)"
    }
    column "group3_created_at" {
      type = "DateTime64(3)"
    }
    column "group4_created_at" {
      type = "DateTime64(3)"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "historical_migration" {
      type = "Bool"
    }
    column "captured_at" {
      type = "DateTime64(6, 'UTC')"
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
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
    column "total_event_size" {
      type = "UInt32"
    }
  }

  materialized_view "kafka_logs34_avro_mv" {
    to_table = "posthog.writable_logs34"
    query    = <<SQL
SELECT
  uuid,
  trace_id,
  span_id,
  trace_flags,
  timestamp,
  observed_timestamp,
  body,
  severity_text,
  severity_number,
  service_name,
  instrumentation_scope,
  event_name,
  mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
  mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
  toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
  observed_timestamp
  + toIntervalDay(
    if(
      (retention_days IS NOT NULL) AND (retention_days > 0),
      retention_days,
      toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(15))
    )
  ) AS original_expiry_timestamp,
  _partition,
  _topic,
  _offset,
  toInt64OrDefault(_headers.value[indexOf(_headers.name, 'record_count')], toInt64(1)) AS _record_count,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_uncompressed')]) / _record_count AS _bytes_uncompressed,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_compressed')]) / _record_count AS _bytes_compressed,
  ifNull(pattern, '') AS pattern,
  toUInt8(ifNull(pattern_version, 0)) AS pattern_version
FROM posthog.kafka_logs_avro
SQL

    column "uuid" {
      type = "String"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "trace_flags" {
      type = "Int32"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "body" {
      type = "String"
    }
    column "severity_text" {
      type = "String"
    }
    column "severity_number" {
      type = "Int32"
    }
    column "service_name" {
      type = "String"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "event_name" {
      type = "String"
    }
    column "attributes_map_str" {
      type = "Map(String, String)"
    }
    column "resource_attributes" {
      type = "Map(String, String)"
    }
    column "team_id" {
      type = "Int32"
    }
    column "original_expiry_timestamp" {
      type = "DateTime64(6)"
    }
    column "_partition" {
      type = "UInt64"
    }
    column "_topic" {
      type = "LowCardinality(String)"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_record_count" {
      type = "Int64"
    }
    column "_bytes_uncompressed" {
      type = "Nullable(Int64)"
    }
    column "_bytes_compressed" {
      type = "Nullable(Int64)"
    }
    column "pattern" {
      type = "String"
    }
    column "pattern_version" {
      type = "UInt8"
    }
  }
}
