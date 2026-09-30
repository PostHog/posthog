database "posthog" {
  table "events_json" {
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "JSON(max_dynamic_paths=0, `$agent_application_id` String, `$agent_revision_id` String, `$agent_session_id` String, `$agent_turn` String, `$ai_audio_cost_usd` String, `$ai_audio_input_tokens` String, `$ai_audio_output_tokens` String, `$ai_batch_run_id` String, `$ai_cache_creation_input_tokens` String, `$ai_cache_read_input_tokens` String, `$ai_error` String, `$ai_error_normalized` String, `$ai_error_type` String, `$ai_evaluation_allows_na` String, `$ai_evaluation_applicable` String, `$ai_evaluation_id` String, `$ai_evaluation_name` String, `$ai_evaluation_reasoning` String, `$ai_evaluation_result` String, `$ai_evaluation_result_type` String, `$ai_evaluation_runtime` String, `$ai_evaluation_skipped` String, `$ai_evaluation_start_time` String, `$ai_evaluation_type` String, `$ai_experiment_id` String, `$ai_framework` String, `$ai_generation_id` String, `$ai_http_status` String, `$ai_image_cost_usd` String, `$ai_image_input_tokens` String, `$ai_image_output_tokens` String, `$ai_input_cost_usd` String, `$ai_input_tokens` String, `$ai_is_error` String, `$ai_latency` String, `$ai_model` String, `$ai_origin` String, `$ai_output_cost_usd` String, `$ai_output_tokens` String, `$ai_parent_id` String, `$ai_prompt_name` String, `$ai_provider` String, `$ai_reasoning_tokens` String, `$ai_request_cost_usd` String, `$ai_sentiment_label` String, `$ai_sentiment_message_count` String, `$ai_sentiment_score` String, `$ai_session_id` String, `$ai_span_id` String, `$ai_span_name` String, `$ai_span_type` String, `$ai_target_event_id` String, `$ai_text_input_tokens` String, `$ai_text_output_tokens` String, `$ai_time_to_first_token` String, `$ai_tools_called` String, `$ai_total_cost_usd` String, `$ai_total_tokens` String, `$ai_trace_id` String, `$ai_trace_name` String, `$ai_video_cost_usd` String, `$ai_video_input_tokens` String, `$ai_video_output_tokens` String, `$ai_web_search_cost_usd` String, `$ai_web_search_count` String, `$anon_distinct_id` String, `$app_build` String, `$app_name` String, `$app_namespace` String, `$app_version` String, `$autocapture_disabled_server_side` LowCardinality(String), `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_language_prefix` String, `$browser_type` String, `$browser_version` LowCardinality(String), `$client_session_initial_pathname` String, `$client_session_initial_referring_host` String, `$client_session_initial_utm_campaign` String, `$client_session_initial_utm_content` String, `$client_session_initial_utm_medium` String, `$client_session_initial_utm_source` String, `$client_session_initial_utm_term` String, `$config_defaults` LowCardinality(String), `$configured_session_timeout_ms` String, `$current_url` String, `$dead_clicks_enabled_server_side` LowCardinality(String), `$device` String, `$device_id` String, `$device_manufacturer` String, `$device_model` String, `$device_name` String, `$device_type` LowCardinality(String), `$el_text` String, `$event_type` String, `$exception_capture_enabled_server_side` LowCardinality(String), `$exception_fingerprint` String, `$exception_functions` Array(String), `$exception_handled` String, `$exception_is_synthetic` String, `$exception_issue_id` String, `$exception_level` String, `$exception_list` Array(JSON(max_dynamic_paths=0, type String, value String)), `$exception_message` String, `$exception_proposed_fingerprint` String, `$exception_sources` Array(String), `$exception_type` String, `$exception_types` Array(String), `$exception_values` Array(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_accuracy_radius` String, `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_latitude` String, `$geoip_longitude` String, `$geoip_postal_code` String, `$geoip_subdivision_1_code` String, `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_subdivision_2_code` String, `$geoip_subdivision_2_name` String, `$geoip_time_zone` LowCardinality(String), `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$groups.instance` String, `$groups.organization` String, `$groups.project` String, `$host` String, `$initial_pathname` String, `$initial_referrer` String, `$initial_referring_domain` String, `$initial_search_engine` String, `$initialization_time` String, `$ip` String, `$is_identified` String, `$lib` String, `$lib_version` LowCardinality(String), `$lib_version__minor` String, `$mcp_client_name` String, `$mcp_client_user_agent` String, `$mcp_duration_ms` String, `$mcp_error_message` String, `$mcp_exec_tool_call_description` String, `$mcp_exec_tool_call_name` String, `$mcp_intent` String, `$mcp_intent_source` String, `$mcp_is_error` String, `$mcp_listed_tool_names` Array(String), `$mcp_oauth_client_name` String, `$mcp_organization_id` String, `$mcp_project_id` String, `$mcp_session_id` String, `$mcp_source` String, `$mcp_tool_category` String, `$mcp_tool_description` String, `$mcp_tool_name` String, `$os` LowCardinality(String), `$os_name` String, `$os_version` LowCardinality(String), `$pageview_id` String, `$pathname` String, `$prev_pageview_max_content_percentage` String, `$prev_pageview_max_scroll_percentage` String, `$prev_pageview_pathname` String, `$process_person_profile` String, `$raw_user_agent` LowCardinality(String), `$recording_status` String, `$referrer` String, `$referring_domain` String, `$replay_minimum_duration` String, `$replay_sample_rate` String, `$screen_height` LowCardinality(String), `$screen_name` String, `$screen_width` LowCardinality(String), `$search_engine` String, `$session_entry_host` String, `$session_entry_pathname` String, `$session_entry_referrer` String, `$session_entry_referring_domain` String, `$session_entry_search_engine` String, `$session_entry_url` String, `$session_entry_utm_campaign` String, `$session_entry_utm_content` String, `$session_entry_utm_medium` String, `$session_entry_utm_source` String, `$session_entry_utm_term` String, `$session_id` String, `$session_recording_event_trigger_activated_session` String, `$session_recording_start_reason` String, `$session_recording_url_trigger_status` String, `$survey_completed` String, `$survey_id` String, `$survey_iteration` String, `$survey_iteration_start_date` String, `$survey_name` String, `$survey_partially_completed` String, `$survey_response` String, `$survey_response_1` String, `$survey_submission_id` String, `$time` String, `$timezone` LowCardinality(String), `$timezone_offset` LowCardinality(String), `$user_id` String, `$viewport_height` String, `$viewport_width` String, `$web_vitals_CLS_value` String, `$web_vitals_FCP_value` String, `$web_vitals_INP_value` String, `$web_vitals_LCP_value` String, `$web_vitals_enabled_server_side` LowCardinality(String), `$window_id` String, _kx String, action String, action_name String, address String, apiErrorMessage String, apiName String, app_name String, app_version String, arguments String, audio_duration String, authentication_method String, auto_chapters String, auto_highlights String, category String, chain String, channel String, client_id String, client_name String, commit_sha String, community_id String, conceptName String, content_length String, content_safety String, context String, contributionError String, created_at String, created_by String, created_by_system String, currentScreen String, current_member_guid String, customer_email String, dclid String, deal_id String, device_type String, disable_institution_search String, disfluencies String, distinct_id String, dual_channel String, duration String, email String, email_domain String, entity_detection String, env String, environment String, epik String, event String, event_count_in_month String, event_count_in_period String, events_projected_amount String, fbclid String, filter_profanity String, filters_count String, function String, gad_source String, gbraid String, gclid String, gclsrc String, gross String, group_id String, historical_migration String, iab_categories String, id String, igshid String, index String, initial__kx String, initial_dclid String, initial_epik String, initial_fbclid String, initial_gad_source String, initial_gbraid String, initial_gclid String, initial_gclsrc String, initial_igshid String, initial_irclid String, initial_li_fat_id String, initial_mc_cid String, initial_msclkid String, initial_qclid String, initial_rdt_cid String, initial_sccid String, initial_step String, initial_ttclid String, initial_twclid String, initial_utm_campaign String, initial_utm_content String, initial_utm_medium String, initial_utm_source String, initial_utm_term String, initial_wbraid String, initiator String, insight String, institution_name String, inviteCode String, irclid String, is_demo_project String, is_first_component_load String, is_first_event_for_user String, is_initial_aggregation String, is_oauth String, is_organization_first_user String, is_test_user String, item_count String, job_type String, key String, kind String, language_detection String, li_fat_id String, machine_id String, mc_cid String, message String, method String, mode String, most_recent_app_os String, msclkid String, name String, nativeBuildVersion String, numberOfSecrets String, orderId String, orderType String, organization String, organization_id String, organization_name String, organizations String, origin String, osName String, owner_type String, page String, payment_status String, phone String, platform String, product String, product_analytics_projected_amount String, product_key String, progress String, protocol String, qclid String, query String, ramp String, rdt_cid String, realm String, `record-id` String, recording_count_in_period String, recordings_projected_amount String, redact_pii String, referrer String, referrer_id String, region String, revenue String, sccid String, screen_name String, sdk String, search_term String, sentiment_analysis String, session_replay_projected_amount String, sku String, source String, speaker_labels String, statusCode String, status_message String, store_url String, stripe_amount_paid String, subdomain String, subscriptionStatus String, summarization String, surface_tag String, survey_responses_count_in_period String, symbol String, tag String, target String, team String, testSessionId String, thread_id String, ticketId String, title String, token String, total_event_actions_count String, total_usd String, ttclid String, twclid String, type String, url String, url_promotion_id String, usd String, user_agent String, user_email_domain String, user_platform String, utm_campaign String, utm_content String, utm_medium String, utm_source String, utm_term String, valid_ach_accounts String, wbraid String, wlo_enabled String, workplace_billing_plan String, workspace String, workspaceId String)"
    }
    column "temporary_properties" {
      type = "JSON(max_dynamic_paths = 32)"
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
      type = "JSON(max_dynamic_paths=0, `$app_build` String, `$app_name` String, `$app_namespace` String, `$app_version` String, `$browser` LowCardinality(String), `$browser_language` String, `$browser_language_prefix` String, `$browser_type` String, `$browser_version` LowCardinality(String), `$current_url` String, `$device` String, `$device_id` String, `$device_manufacturer` String, `$device_model` String, `$device_name` String, `$device_type` LowCardinality(String), `$email` String, `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_postal_code` String, `$geoip_subdivision_1_code` String, `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_subdivision_2_code` String, `$geoip_subdivision_2_name` String, `$geoip_time_zone` LowCardinality(String), `$initial__kx` String, `$initial_app_build` String, `$initial_app_name` String, `$initial_app_namespace` String, `$initial_app_version` String, `$initial_browser` LowCardinality(String), `$initial_browser_language` String, `$initial_browser_language_prefix` String, `$initial_browser_type` String, `$initial_browser_version` LowCardinality(String), `$initial_current_url` String, `$initial_dclid` String, `$initial_device` String, `$initial_device_id` String, `$initial_device_manufacturer` String, `$initial_device_model` String, `$initial_device_name` String, `$initial_device_type` LowCardinality(String), `$initial_epik` String, `$initial_fbclid` String, `$initial_gad_source` String, `$initial_gbraid` String, `$initial_gclid` String, `$initial_gclsrc` String, `$initial_geoip_city_name` String, `$initial_geoip_continent_code` String, `$initial_geoip_continent_name` String, `$initial_geoip_country_code` String, `$initial_geoip_country_name` LowCardinality(String), `$initial_geoip_postal_code` String, `$initial_geoip_subdivision_1_code` String, `$initial_geoip_subdivision_1_name` LowCardinality(String), `$initial_geoip_subdivision_2_code` String, `$initial_geoip_subdivision_2_name` String, `$initial_geoip_time_zone` LowCardinality(String), `$initial_igshid` String, `$initial_irclid` String, `$initial_li_fat_id` String, `$initial_mc_cid` String, `$initial_msclkid` String, `$initial_os` LowCardinality(String), `$initial_os_name` String, `$initial_os_version` LowCardinality(String), `$initial_pathname` String, `$initial_qclid` String, `$initial_raw_user_agent` LowCardinality(String), `$initial_rdt_cid` String, `$initial_referrer` String, `$initial_referring_domain` String, `$initial_sccid` String, `$initial_screen_height` LowCardinality(String), `$initial_screen_width` LowCardinality(String), `$initial_search_engine` String, `$initial_ttclid` String, `$initial_twclid` String, `$initial_utm_campaign` String, `$initial_utm_content` String, `$initial_utm_medium` String, `$initial_utm_source` String, `$initial_utm_term` String, `$initial_viewport_height` String, `$initial_viewport_width` String, `$initial_wbraid` String, `$last_seen_survey_date` String, `$organization_id` String, `$os` LowCardinality(String), `$os_name` String, `$os_version` LowCardinality(String), `$pathname` String, `$product_tour_last_seen_date` String, `$raw_user_agent` LowCardinality(String), `$referrer` String, `$referring_domain` String, `$screen_height` LowCardinality(String), `$screen_width` LowCardinality(String), `$search_engine` String, `$survey_last_seen_date` String, `$viewport_height` String, `$viewport_width` String, `Email Domain` String, _kx String, companyName String, customer String, dclid String, email String, epik String, fbclid String, first_name String, gad_source String, gbraid String, gclid String, gclsrc String, hubspot_score String, icp_role String, id String, igshid String, irclid String, is_email_verified String, is_signed_up String, last_name String, li_fat_id String, mc_cid String, msclkid String, name String, organization_id String, organization_member_count String, qclid String, rdt_cid String, role String, role_at_organization String, sccid String, serverMarketing String, serverMasterclass String, ttclid String, twclid String, user_email_domain String, username String, utm_campaign String, utm_content String, utm_medium String, utm_source String, utm_term String, val_region String, wbraid String)"
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
    column "elements_chain_href" {
      type = "String"
    }
    column "elements_chain_texts" {
      type = "Array(String)"
    }
    column "elements_chain_ids" {
      type = "Array(String)"
    }
    column "elements_chain_elements" {
      type = "Array(Enum8('a'=1, 'button'=2, 'form'=3, 'input'=4, 'select'=5, 'textarea'=6, 'label'=7))"
    }
    column "$group_0" {
      type = "String"
      alias = "ifNull(properties.`$group_0`, '')"
    }
    column "$group_1" {
      type = "String"
      alias = "ifNull(properties.`$group_1`, '')"
    }
    column "$group_2" {
      type = "String"
      alias = "ifNull(properties.`$group_2`, '')"
    }
    column "$group_3" {
      type = "String"
      alias = "ifNull(properties.`$group_3`, '')"
    }
    column "$group_4" {
      type = "String"
      alias = "ifNull(properties.`$group_4`, '')"
    }
    column "$window_id" {
      type = "String"
      alias = "ifNull(properties.`$window_id`, '')"
    }
    column "$session_id" {
      type = "String"
      alias = "ifNull(properties.`$session_id`, '')"
    }
    column "$session_id_uuid" {
      type = "Nullable(UInt128)"
      alias = "toUInt128(toUUIDOrNull(properties.`$session_id`))"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_events_json"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }
  table "sharded_events_json" {
    order_by     = ["team_id", "toDate(timestamp)", "event", "cityHash64(distinct_id)", "timestamp", "uuid"]
    partition_by = "clamp(toYYYYMM(timestamp), 202001, 203512)"
    primary_key  = ["team_id", "toDate(timestamp)", "event", "cityHash64(distinct_id)"]
    sample_by    = "cityHash64(distinct_id)"
    settings = {
      index_granularity                                             = "8192"
      enable_block_number_column                                    = "1"
      enable_block_offset_column                                    = "1"
      map_serialization_version                                     = "with_buckets"
      string_serialization_version = "single_stream"
      propagate_types_serialization_versions_to_nested_types = "1"
      object_serialization_version                                  = "v3"
      object_shared_data_serialization_version                      = "map_with_buckets"
    }
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "JSON(max_dynamic_paths=0, `$agent_application_id` String, `$agent_revision_id` String, `$agent_session_id` String, `$agent_turn` String, `$ai_audio_cost_usd` String, `$ai_audio_input_tokens` String, `$ai_audio_output_tokens` String, `$ai_batch_run_id` String, `$ai_cache_creation_input_tokens` String, `$ai_cache_read_input_tokens` String, `$ai_error` String, `$ai_error_normalized` String, `$ai_error_type` String, `$ai_evaluation_allows_na` String, `$ai_evaluation_applicable` String, `$ai_evaluation_id` String, `$ai_evaluation_name` String, `$ai_evaluation_reasoning` String, `$ai_evaluation_result` String, `$ai_evaluation_result_type` String, `$ai_evaluation_runtime` String, `$ai_evaluation_skipped` String, `$ai_evaluation_start_time` String, `$ai_evaluation_type` String, `$ai_experiment_id` String, `$ai_framework` String, `$ai_generation_id` String, `$ai_http_status` String, `$ai_image_cost_usd` String, `$ai_image_input_tokens` String, `$ai_image_output_tokens` String, `$ai_input_cost_usd` String, `$ai_input_tokens` String, `$ai_is_error` String, `$ai_latency` String, `$ai_model` String, `$ai_origin` String, `$ai_output_cost_usd` String, `$ai_output_tokens` String, `$ai_parent_id` String, `$ai_prompt_name` String, `$ai_provider` String, `$ai_reasoning_tokens` String, `$ai_request_cost_usd` String, `$ai_sentiment_label` String, `$ai_sentiment_message_count` String, `$ai_sentiment_score` String, `$ai_session_id` String, `$ai_span_id` String, `$ai_span_name` String, `$ai_span_type` String, `$ai_target_event_id` String, `$ai_text_input_tokens` String, `$ai_text_output_tokens` String, `$ai_time_to_first_token` String, `$ai_tools_called` String, `$ai_total_cost_usd` String, `$ai_total_tokens` String, `$ai_trace_id` String, `$ai_trace_name` String, `$ai_video_cost_usd` String, `$ai_video_input_tokens` String, `$ai_video_output_tokens` String, `$ai_web_search_cost_usd` String, `$ai_web_search_count` String, `$anon_distinct_id` String, `$app_build` String, `$app_name` String, `$app_namespace` String, `$app_version` String, `$autocapture_disabled_server_side` LowCardinality(String), `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_language_prefix` String, `$browser_type` String, `$browser_version` LowCardinality(String), `$client_session_initial_pathname` String, `$client_session_initial_referring_host` String, `$client_session_initial_utm_campaign` String, `$client_session_initial_utm_content` String, `$client_session_initial_utm_medium` String, `$client_session_initial_utm_source` String, `$client_session_initial_utm_term` String, `$config_defaults` LowCardinality(String), `$configured_session_timeout_ms` String, `$current_url` String, `$dead_clicks_enabled_server_side` LowCardinality(String), `$device` String, `$device_id` String, `$device_manufacturer` String, `$device_model` String, `$device_name` String, `$device_type` LowCardinality(String), `$el_text` String, `$event_type` String, `$exception_capture_enabled_server_side` LowCardinality(String), `$exception_fingerprint` String, `$exception_functions` Array(String), `$exception_handled` String, `$exception_is_synthetic` String, `$exception_issue_id` String, `$exception_level` String, `$exception_list` Array(JSON(max_dynamic_paths=0, type String, value String)), `$exception_message` String, `$exception_proposed_fingerprint` String, `$exception_sources` Array(String), `$exception_type` String, `$exception_types` Array(String), `$exception_values` Array(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_accuracy_radius` String, `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_latitude` String, `$geoip_longitude` String, `$geoip_postal_code` String, `$geoip_subdivision_1_code` String, `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_subdivision_2_code` String, `$geoip_subdivision_2_name` String, `$geoip_time_zone` LowCardinality(String), `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$groups.instance` String, `$groups.organization` String, `$groups.project` String, `$host` String, `$initial_pathname` String, `$initial_referrer` String, `$initial_referring_domain` String, `$initial_search_engine` String, `$initialization_time` String, `$ip` String, `$is_identified` String, `$lib` String, `$lib_version` LowCardinality(String), `$lib_version__minor` String, `$mcp_client_name` String, `$mcp_client_user_agent` String, `$mcp_duration_ms` String, `$mcp_error_message` String, `$mcp_exec_tool_call_description` String, `$mcp_exec_tool_call_name` String, `$mcp_intent` String, `$mcp_intent_source` String, `$mcp_is_error` String, `$mcp_listed_tool_names` Array(String), `$mcp_oauth_client_name` String, `$mcp_organization_id` String, `$mcp_project_id` String, `$mcp_session_id` String, `$mcp_source` String, `$mcp_tool_category` String, `$mcp_tool_description` String, `$mcp_tool_name` String, `$os` LowCardinality(String), `$os_name` String, `$os_version` LowCardinality(String), `$pageview_id` String, `$pathname` String, `$prev_pageview_max_content_percentage` String, `$prev_pageview_max_scroll_percentage` String, `$prev_pageview_pathname` String, `$process_person_profile` String, `$raw_user_agent` LowCardinality(String), `$recording_status` String, `$referrer` String, `$referring_domain` String, `$replay_minimum_duration` String, `$replay_sample_rate` String, `$screen_height` LowCardinality(String), `$screen_name` String, `$screen_width` LowCardinality(String), `$search_engine` String, `$session_entry_host` String, `$session_entry_pathname` String, `$session_entry_referrer` String, `$session_entry_referring_domain` String, `$session_entry_search_engine` String, `$session_entry_url` String, `$session_entry_utm_campaign` String, `$session_entry_utm_content` String, `$session_entry_utm_medium` String, `$session_entry_utm_source` String, `$session_entry_utm_term` String, `$session_id` String, `$session_recording_event_trigger_activated_session` String, `$session_recording_start_reason` String, `$session_recording_url_trigger_status` String, `$survey_completed` String, `$survey_id` String, `$survey_iteration` String, `$survey_iteration_start_date` String, `$survey_name` String, `$survey_partially_completed` String, `$survey_response` String, `$survey_response_1` String, `$survey_submission_id` String, `$time` String, `$timezone` LowCardinality(String), `$timezone_offset` LowCardinality(String), `$user_id` String, `$viewport_height` String, `$viewport_width` String, `$web_vitals_CLS_value` String, `$web_vitals_FCP_value` String, `$web_vitals_INP_value` String, `$web_vitals_LCP_value` String, `$web_vitals_enabled_server_side` LowCardinality(String), `$window_id` String, _kx String, action String, action_name String, address String, apiErrorMessage String, apiName String, app_name String, app_version String, arguments String, audio_duration String, authentication_method String, auto_chapters String, auto_highlights String, category String, chain String, channel String, client_id String, client_name String, commit_sha String, community_id String, conceptName String, content_length String, content_safety String, context String, contributionError String, created_at String, created_by String, created_by_system String, currentScreen String, current_member_guid String, customer_email String, dclid String, deal_id String, device_type String, disable_institution_search String, disfluencies String, distinct_id String, dual_channel String, duration String, email String, email_domain String, entity_detection String, env String, environment String, epik String, event String, event_count_in_month String, event_count_in_period String, events_projected_amount String, fbclid String, filter_profanity String, filters_count String, function String, gad_source String, gbraid String, gclid String, gclsrc String, gross String, group_id String, historical_migration String, iab_categories String, id String, igshid String, index String, initial__kx String, initial_dclid String, initial_epik String, initial_fbclid String, initial_gad_source String, initial_gbraid String, initial_gclid String, initial_gclsrc String, initial_igshid String, initial_irclid String, initial_li_fat_id String, initial_mc_cid String, initial_msclkid String, initial_qclid String, initial_rdt_cid String, initial_sccid String, initial_step String, initial_ttclid String, initial_twclid String, initial_utm_campaign String, initial_utm_content String, initial_utm_medium String, initial_utm_source String, initial_utm_term String, initial_wbraid String, initiator String, insight String, institution_name String, inviteCode String, irclid String, is_demo_project String, is_first_component_load String, is_first_event_for_user String, is_initial_aggregation String, is_oauth String, is_organization_first_user String, is_test_user String, item_count String, job_type String, key String, kind String, language_detection String, li_fat_id String, machine_id String, mc_cid String, message String, method String, mode String, most_recent_app_os String, msclkid String, name String, nativeBuildVersion String, numberOfSecrets String, orderId String, orderType String, organization String, organization_id String, organization_name String, organizations String, origin String, osName String, owner_type String, page String, payment_status String, phone String, platform String, product String, product_analytics_projected_amount String, product_key String, progress String, protocol String, qclid String, query String, ramp String, rdt_cid String, realm String, `record-id` String, recording_count_in_period String, recordings_projected_amount String, redact_pii String, referrer String, referrer_id String, region String, revenue String, sccid String, screen_name String, sdk String, search_term String, sentiment_analysis String, session_replay_projected_amount String, sku String, source String, speaker_labels String, statusCode String, status_message String, store_url String, stripe_amount_paid String, subdomain String, subscriptionStatus String, summarization String, surface_tag String, survey_responses_count_in_period String, symbol String, tag String, target String, team String, testSessionId String, thread_id String, ticketId String, title String, token String, total_event_actions_count String, total_usd String, ttclid String, twclid String, type String, url String, url_promotion_id String, usd String, user_agent String, user_email_domain String, user_platform String, utm_campaign String, utm_content String, utm_medium String, utm_source String, utm_term String, valid_ach_accounts String, wbraid String, wlo_enabled String, workplace_billing_plan String, workspace String, workspaceId String)"
    }
    column "temporary_properties" {
      type = "JSON(max_dynamic_paths = 32)"
      ttl = "toDateTime(inserted_at) + toIntervalDay(60)"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
      codec = "GCD, Default"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "created_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
      codec = "GCD, Default"
    }
    column "_timestamp" {
      type = "DateTime"
      codec = "T64, Default"
    }
    column "_offset" {
      type = "UInt64"
      codec = "T64, Default"
    }
    column "elements_chain" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    column "person_properties" {
      type = "JSON(max_dynamic_paths=0, `$app_build` String, `$app_name` String, `$app_namespace` String, `$app_version` String, `$browser` LowCardinality(String), `$browser_language` String, `$browser_language_prefix` String, `$browser_type` String, `$browser_version` LowCardinality(String), `$current_url` String, `$device` String, `$device_id` String, `$device_manufacturer` String, `$device_model` String, `$device_name` String, `$device_type` LowCardinality(String), `$email` String, `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_postal_code` String, `$geoip_subdivision_1_code` String, `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_subdivision_2_code` String, `$geoip_subdivision_2_name` String, `$geoip_time_zone` LowCardinality(String), `$initial__kx` String, `$initial_app_build` String, `$initial_app_name` String, `$initial_app_namespace` String, `$initial_app_version` String, `$initial_browser` LowCardinality(String), `$initial_browser_language` String, `$initial_browser_language_prefix` String, `$initial_browser_type` String, `$initial_browser_version` LowCardinality(String), `$initial_current_url` String, `$initial_dclid` String, `$initial_device` String, `$initial_device_id` String, `$initial_device_manufacturer` String, `$initial_device_model` String, `$initial_device_name` String, `$initial_device_type` LowCardinality(String), `$initial_epik` String, `$initial_fbclid` String, `$initial_gad_source` String, `$initial_gbraid` String, `$initial_gclid` String, `$initial_gclsrc` String, `$initial_geoip_city_name` String, `$initial_geoip_continent_code` String, `$initial_geoip_continent_name` String, `$initial_geoip_country_code` String, `$initial_geoip_country_name` LowCardinality(String), `$initial_geoip_postal_code` String, `$initial_geoip_subdivision_1_code` String, `$initial_geoip_subdivision_1_name` LowCardinality(String), `$initial_geoip_subdivision_2_code` String, `$initial_geoip_subdivision_2_name` String, `$initial_geoip_time_zone` LowCardinality(String), `$initial_igshid` String, `$initial_irclid` String, `$initial_li_fat_id` String, `$initial_mc_cid` String, `$initial_msclkid` String, `$initial_os` LowCardinality(String), `$initial_os_name` String, `$initial_os_version` LowCardinality(String), `$initial_pathname` String, `$initial_qclid` String, `$initial_raw_user_agent` LowCardinality(String), `$initial_rdt_cid` String, `$initial_referrer` String, `$initial_referring_domain` String, `$initial_sccid` String, `$initial_screen_height` LowCardinality(String), `$initial_screen_width` LowCardinality(String), `$initial_search_engine` String, `$initial_ttclid` String, `$initial_twclid` String, `$initial_utm_campaign` String, `$initial_utm_content` String, `$initial_utm_medium` String, `$initial_utm_source` String, `$initial_utm_term` String, `$initial_viewport_height` String, `$initial_viewport_width` String, `$initial_wbraid` String, `$last_seen_survey_date` String, `$organization_id` String, `$os` LowCardinality(String), `$os_name` String, `$os_version` LowCardinality(String), `$pathname` String, `$product_tour_last_seen_date` String, `$raw_user_agent` LowCardinality(String), `$referrer` String, `$referring_domain` String, `$screen_height` LowCardinality(String), `$screen_width` LowCardinality(String), `$search_engine` String, `$survey_last_seen_date` String, `$viewport_height` String, `$viewport_width` String, `Email Domain` String, _kx String, companyName String, customer String, dclid String, email String, epik String, fbclid String, first_name String, gad_source String, gbraid String, gclid String, gclsrc String, hubspot_score String, icp_role String, id String, igshid String, irclid String, is_email_verified String, is_signed_up String, last_name String, li_fat_id String, mc_cid String, msclkid String, name String, organization_id String, organization_member_count String, qclid String, rdt_cid String, role String, role_at_organization String, sccid String, serverMarketing String, serverMasterclass String, ttclid String, twclid String, user_email_domain String, username String, utm_campaign String, utm_content String, utm_medium String, utm_source String, utm_term String, val_region String, wbraid String)"
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
    column "person_created_at" {
      type = "DateTime64(3)"
      codec = "GCD, Default"
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
      codec = "GCD, Default"
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
      codec = "T64, Default"
    }
    column "captured_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
      codec = "GCD, Default"
    }
    column "_partition" {
      type = "UInt64"
      codec = "T64, Default"
    }
    column "elements_chain_href" {
      type = "String"
      materialized = "EXTRACT(elements_chain, '(?::|\")href=\"(.*?)\"')"
    }
    column "elements_chain_texts" {
      type = "Array(String)"
      materialized = "arrayDistinct(extractAll(elements_chain, '(?::|\")text=\"(.*?)\"'))"
    }
    column "elements_chain_ids" {
      type = "Array(String)"
      materialized = "arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id=\"(.*?)\"'))"
    }
    column "elements_chain_elements" {
      type = "Array(Enum8('a'=1, 'button'=2, 'form'=3, 'input'=4, 'select'=5, 'textarea'=6, 'label'=7))"
      materialized = "arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\\\.|$|:)'))"
    }
    index "bloom_filter_distinct_id" {
      expr        = "distinct_id"
      type        = "bloom_filter"
      granularity = 1
    }
    index "bloom_filter_uuid" {
      expr        = "uuid"
      type        = "bloom_filter"
      granularity = 1
    }
    index "bloom_filter_person_id" {
      expr        = "person_id"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_captured_at" {
      expr        = "captured_at"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_kafka_timestamp" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_inserted_at" {
      expr        = "inserted_at"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_timestamp" {
      expr        = "timestamp"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_historical_migration" {
      expr        = "historical_migration"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_created_at" {
      expr        = "created_at"
      type        = "minmax"
      granularity = 1
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.events_json"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }

  table "kafka_events_json" {
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
    engine "kafka" {
      collection           = "msk_cluster"
      topic_list           = "clickhouse_events_json"
      group_name           = "group1"
      format               = "JSONEachRow"
      skip_broken_messages = 100
    }
  }
  table "kafka_performance_events" {
    column "uuid" {
      type = "UUID"
    }
    column "session_id" {
      type = "String"
    }
    column "window_id" {
      type = "String"
    }
    column "pageview_id" {
      type = "String"
    }
    column "distinct_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(3)"
    }
    column "time_origin" {
      type = "DateTime64(3, 'UTC')"
    }
    column "entry_type" {
      type = "LowCardinality(String)"
    }
    column "name" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "current_url" {
      type = "String"
    }
    column "start_time" {
      type = "Float64"
    }
    column "duration" {
      type = "Float64"
    }
    column "redirect_start" {
      type = "Float64"
    }
    column "redirect_end" {
      type = "Float64"
    }
    column "worker_start" {
      type = "Float64"
    }
    column "fetch_start" {
      type = "Float64"
    }
    column "domain_lookup_start" {
      type = "Float64"
    }
    column "domain_lookup_end" {
      type = "Float64"
    }
    column "connect_start" {
      type = "Float64"
    }
    column "secure_connection_start" {
      type = "Float64"
    }
    column "connect_end" {
      type = "Float64"
    }
    column "request_start" {
      type = "Float64"
    }
    column "response_start" {
      type = "Float64"
    }
    column "response_end" {
      type = "Float64"
    }
    column "decoded_body_size" {
      type = "Int64"
    }
    column "encoded_body_size" {
      type = "Int64"
    }
    column "initiator_type" {
      type = "LowCardinality(String)"
    }
    column "next_hop_protocol" {
      type = "LowCardinality(String)"
    }
    column "render_blocking_status" {
      type = "LowCardinality(String)"
    }
    column "response_status" {
      type = "Int64"
    }
    column "transfer_size" {
      type = "Int64"
    }
    column "largest_contentful_paint_element" {
      type = "String"
    }
    column "largest_contentful_paint_render_time" {
      type = "Float64"
    }
    column "largest_contentful_paint_load_time" {
      type = "Float64"
    }
    column "largest_contentful_paint_size" {
      type = "Float64"
    }
    column "largest_contentful_paint_id" {
      type = "String"
    }
    column "largest_contentful_paint_url" {
      type = "String"
    }
    column "dom_complete" {
      type = "Float64"
    }
    column "dom_content_loaded_event" {
      type = "Float64"
    }
    column "dom_interactive" {
      type = "Float64"
    }
    column "load_event_end" {
      type = "Float64"
    }
    column "load_event_start" {
      type = "Float64"
    }
    column "redirect_count" {
      type = "Int64"
    }
    column "navigation_type" {
      type = "LowCardinality(String)"
    }
    column "unload_event_end" {
      type = "Float64"
    }
    column "unload_event_start" {
      type = "Float64"
    }
    engine "kafka" {
      collection = "msk_cluster"
      topic_list = "clickhouse_performance_events"
      group_name = "group1"
      format     = "JSONEachRow"
    }
  }
  table "kafka_person_distinct_id" {
    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    column "team_id" {
      type = "Int64"
    }
    column "_sign" {
      type = "Nullable(Int8)"
    }
    column "is_deleted" {
      type = "Nullable(Int8)"
    }
    engine "kafka" {
      collection = "msk_cluster"
      topic_list = "clickhouse_person_unique_id"
      group_name = "group1"
      format     = "JSONEachRow"
    }
  }
  table "kafka_person_overrides" {
    column "team_id" {
      type = "Int32"
    }
    column "old_person_id" {
      type = "UUID"
    }
    column "override_person_id" {
      type = "UUID"
    }
    column "merged_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "oldest_event" {
      type = "DateTime64(6, 'UTC')"
    }
    column "version" {
      type = "Int32"
    }
    engine "kafka" {
      broker_list = "kafka:9092"
      topic_list  = "clickhouse_person_override"
      group_name  = "clickhouse-person-overrides"
      format      = "JSONEachRow"
    }
  }
  table "partitioned_sharded_posthog_document_embeddings" {
    order_by     = ["team_id", "toDate(timestamp)", "product", "document_type", "model_name", "rendering", "cityHash64(document_id)"]
    partition_by = "toMonday(timestamp)"
    ttl          = "timestamp + toIntervalMonth(3)"
    settings = {
      index_granularity   = "512"
      ttl_only_drop_parts = "1"
    }
    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
      type = "LowCardinality(String)"
    }
    column "model_name" {
      type = "LowCardinality(String)"
    }
    column "rendering" {
      type = "LowCardinality(String)"
    }
    column "document_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(3, 'UTC')"
    }
    column "inserted_at" {
      type = "DateTime64(3, 'UTC')"
    }
    column "content" {
      type    = "String"
      default = "''"
    }
    column "metadata" {
      type    = "String"
      default = "'{}'"
    }
    column "embedding" {
      type = "Array(Float64)"
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
    index "kafka_timestamp_minmax_partitioned_sharded_posthog_document_embeddings" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.partitioned_sharded_posthog_document_embeddings"
      replica_name   = "{replica}"
      version_column = "inserted_at"
    }
  }
  table "query_log_archive_v2" {
    order_by     = ["team_id", "event_date", "event_time", "query_id"]
    partition_by = "toYYYYMM(event_date)"
    settings = {
      index_granularity = "8192"
    }
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
    column "exception_name" {
      type  = "String"
      alias = "errorCodeToName(exception_code)"
    }
    column "exception" {
      type = "String"
    }
    column "stack_trace" {
      type = "String"
    }
    column "ProfileEvents_RealTimeMicroseconds" {
      type = "Int64"
    }
    column "ProfileEvents_OSCPUVirtualTimeMicroseconds" {
      type = "Int64"
    }
    column "ProfileEvents_S3Clients" {
      type = "Int64"
    }
    column "ProfileEvents_S3DeleteObjects" {
      type = "Int64"
    }
    column "ProfileEvents_S3CopyObject" {
      type = "Int64"
    }
    column "ProfileEvents_S3ListObjects" {
      type = "Int64"
    }
    column "ProfileEvents_S3HeadObject" {
      type = "Int64"
    }
    column "ProfileEvents_S3GetObjectAttributes" {
      type = "Int64"
    }
    column "ProfileEvents_S3CreateMultipartUpload" {
      type = "Int64"
    }
    column "ProfileEvents_S3UploadPartCopy" {
      type = "Int64"
    }
    column "ProfileEvents_S3UploadPart" {
      type = "Int64"
    }
    column "ProfileEvents_S3AbortMultipartUpload" {
      type = "Int64"
    }
    column "ProfileEvents_S3CompleteMultipartUpload" {
      type = "Int64"
    }
    column "ProfileEvents_S3PutObject" {
      type = "Int64"
    }
    column "ProfileEvents_S3GetObject" {
      type = "Int64"
    }
    column "ProfileEvents_ReadBufferFromS3Bytes" {
      type = "Int64"
    }
    column "ProfileEvents_WriteBufferFromS3Bytes" {
      type = "Int64"
    }
    column "ProfileEvents" {
      type = "Map(String, UInt64)"
    }
    column "lc_workflow" {
      type = "LowCardinality(String)"
    }
    column "lc_kind" {
      type = "LowCardinality(String)"
    }
    column "lc_id" {
      type = "String"
    }
    column "lc_route_id" {
      type = "String"
    }
    column "lc_access_method" {
      type = "LowCardinality(String)"
    }
    column "lc_api_key_label" {
      type = "String"
    }
    column "lc_api_key_mask" {
      type = "String"
    }
    column "lc_query_type" {
      type = "LowCardinality(String)"
    }
    column "lc_product" {
      type = "LowCardinality(String)"
    }
    column "lc_chargeable" {
      type = "Bool"
    }
    column "lc_name" {
      type = "String"
    }
    column "lc_request_name" {
      type = "String"
    }
    column "lc_client_query_id" {
      type = "String"
    }
    column "lc_org_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "lc_user_id" {
      type = "Int64"
    }
    column "lc_is_impersonated" {
      type = "Bool"
    }
    column "lc_session_id" {
      type = "String"
    }
    column "lc_dashboard_id" {
      type = "Int64"
    }
    column "lc_insight_id" {
      type = "Int64"
    }
    column "lc_cohort_id" {
      type = "Int64"
    }
    column "lc_batch_export_id" {
      type = "String"
    }
    column "lc_experiment_id" {
      type = "Int64"
    }
    column "lc_experiment_feature_flag_key" {
      type = "String"
    }
    column "lc_alert_config_id" {
      type = "String"
    }
    column "lc_feature" {
      type = "LowCardinality(String)"
    }
    column "lc_table_id" {
      type = "String"
    }
    column "lc_warehouse_query" {
      type = "Bool"
    }
    column "lc_person_on_events_mode" {
      type = "LowCardinality(String)"
    }
    column "lc_service_name" {
      type = "String"
    }
    column "lc_workload" {
      type = "LowCardinality(String)"
    }
    column "lc_query__kind" {
      type = "LowCardinality(String)"
    }
    column "lc_query__query" {
      type = "String"
    }
    column "lc_query" {
      type = "String"
    }
    column "lc_temporal__workflow_namespace" {
      type = "String"
    }
    column "lc_temporal__workflow_type" {
      type = "String"
    }
    column "lc_temporal__workflow_id" {
      type = "String"
    }
    column "lc_temporal__workflow_run_id" {
      type = "String"
    }
    column "lc_temporal__activity_type" {
      type = "String"
    }
    column "lc_temporal__activity_id" {
      type = "String"
    }
    column "lc_temporal__attempt" {
      type = "Int64"
    }
    column "lc_dagster__job_name" {
      type = "String"
    }
    column "lc_dagster__run_id" {
      type = "String"
    }
    column "lc_dagster__owner" {
      type = "String"
    }
    column "lc_modifiers" {
      type = "String"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.query_log_archive_new"
      replica_name = "{replica}-{shard}"
    }
  }
  table "sharded_query_log_archive_old" {
    order_by     = ["team_id", "event_date", "event_time", "query_id"]
    partition_by = "toYYYYMM(event_date)"
    settings = {
      index_granularity = "8192"
    }
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
    column "exception_name" {
      type  = "String"
      alias = "errorCodeToName(exception_code)"
    }
    column "exception" {
      type = "String"
    }
    column "stack_trace" {
      type = "String"
    }
    column "ProfileEvents_RealTimeMicroseconds" {
      type = "Int64"
    }
    column "ProfileEvents_OSCPUVirtualTimeMicroseconds" {
      type = "Int64"
    }
    column "ProfileEvents_S3Clients" {
      type = "Int64"
    }
    column "ProfileEvents_S3DeleteObjects" {
      type = "Int64"
    }
    column "ProfileEvents_S3CopyObject" {
      type = "Int64"
    }
    column "ProfileEvents_S3ListObjects" {
      type = "Int64"
    }
    column "ProfileEvents_S3HeadObject" {
      type = "Int64"
    }
    column "ProfileEvents_S3GetObjectAttributes" {
      type = "Int64"
    }
    column "ProfileEvents_S3CreateMultipartUpload" {
      type = "Int64"
    }
    column "ProfileEvents_S3UploadPartCopy" {
      type = "Int64"
    }
    column "ProfileEvents_S3UploadPart" {
      type = "Int64"
    }
    column "ProfileEvents_S3AbortMultipartUpload" {
      type = "Int64"
    }
    column "ProfileEvents_S3CompleteMultipartUpload" {
      type = "Int64"
    }
    column "ProfileEvents_S3PutObject" {
      type = "Int64"
    }
    column "ProfileEvents_S3GetObject" {
      type = "Int64"
    }
    column "ProfileEvents_ReadBufferFromS3Bytes" {
      type = "Int64"
    }
    column "ProfileEvents_WriteBufferFromS3Bytes" {
      type = "Int64"
    }
    column "ProfileEvents" {
      type = "Map(String, UInt64)"
    }
    column "lc_workflow" {
      type = "LowCardinality(String)"
    }
    column "lc_kind" {
      type = "LowCardinality(String)"
    }
    column "lc_id" {
      type = "String"
    }
    column "lc_route_id" {
      type = "String"
    }
    column "lc_access_method" {
      type = "LowCardinality(String)"
    }
    column "lc_api_key_label" {
      type = "String"
    }
    column "lc_api_key_mask" {
      type = "String"
    }
    column "lc_query_type" {
      type = "LowCardinality(String)"
    }
    column "lc_product" {
      type = "LowCardinality(String)"
    }
    column "lc_chargeable" {
      type = "Bool"
    }
    column "lc_name" {
      type = "String"
    }
    column "lc_request_name" {
      type = "String"
    }
    column "lc_client_query_id" {
      type = "String"
    }
    column "lc_org_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "lc_user_id" {
      type = "Int64"
    }
    column "lc_is_impersonated" {
      type = "Bool"
    }
    column "lc_session_id" {
      type = "String"
    }
    column "lc_dashboard_id" {
      type = "Int64"
    }
    column "lc_insight_id" {
      type = "Int64"
    }
    column "lc_cohort_id" {
      type = "Int64"
    }
    column "lc_batch_export_id" {
      type = "String"
    }
    column "lc_experiment_id" {
      type = "Int64"
    }
    column "lc_experiment_feature_flag_key" {
      type = "String"
    }
    column "lc_alert_config_id" {
      type = "String"
    }
    column "lc_feature" {
      type = "LowCardinality(String)"
    }
    column "lc_table_id" {
      type = "String"
    }
    column "lc_warehouse_query" {
      type = "Bool"
    }
    column "lc_person_on_events_mode" {
      type = "LowCardinality(String)"
    }
    column "lc_service_name" {
      type = "String"
    }
    column "lc_workload" {
      type = "LowCardinality(String)"
    }
    column "lc_query__kind" {
      type = "LowCardinality(String)"
    }
    column "lc_query__query" {
      type = "String"
    }
    column "lc_query" {
      type = "String"
    }
    column "lc_temporal__workflow_namespace" {
      type = "String"
    }
    column "lc_temporal__workflow_type" {
      type = "String"
    }
    column "lc_temporal__workflow_id" {
      type = "String"
    }
    column "lc_temporal__workflow_run_id" {
      type = "String"
    }
    column "lc_temporal__activity_type" {
      type = "String"
    }
    column "lc_temporal__activity_id" {
      type = "String"
    }
    column "lc_temporal__attempt" {
      type = "Int64"
    }
    column "lc_dagster__job_name" {
      type = "String"
    }
    column "lc_dagster__run_id" {
      type = "String"
    }
    column "lc_dagster__owner" {
      type = "String"
    }
    column "lc_modifiers" {
      type = "String"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.sharded_query_log_archive"
      replica_name = "{replica}"
    }
  }
  materialized_view "events_json_mv" {
    to_table = "posthog.writable_events"
    query    = file("sql/events_json_mv.sql")

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
    column "person_created_at" {
      type = "DateTime64(3)"
    }
    column "person_properties" {
      type = "String"
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
    column "_timestamp" {
      type = "Nullable(DateTime)"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
  }
  materialized_view "events_recent_json_mv" {
    to_table = "posthog.writable_events_recent"
    query    = file("sql/events_recent_json_mv.sql")

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
    column "person_created_at" {
      type = "DateTime64(3)"
    }
    column "person_properties" {
      type = "String"
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
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
  }
  materialized_view "performance_events_mv" {
    to_table = "posthog.writeable_performance_events"
    query    = file("sql/performance_events_mv.sql")

    column "uuid" {
      type = "UUID"
    }
    column "session_id" {
      type = "String"
    }
    column "window_id" {
      type = "String"
    }
    column "pageview_id" {
      type = "String"
    }
    column "distinct_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(3)"
    }
    column "time_origin" {
      type = "DateTime64(3, 'UTC')"
    }
    column "entry_type" {
      type = "LowCardinality(String)"
    }
    column "name" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "current_url" {
      type = "String"
    }
    column "start_time" {
      type = "Float64"
    }
    column "duration" {
      type = "Float64"
    }
    column "redirect_start" {
      type = "Float64"
    }
    column "redirect_end" {
      type = "Float64"
    }
    column "worker_start" {
      type = "Float64"
    }
    column "fetch_start" {
      type = "Float64"
    }
    column "domain_lookup_start" {
      type = "Float64"
    }
    column "domain_lookup_end" {
      type = "Float64"
    }
    column "connect_start" {
      type = "Float64"
    }
    column "secure_connection_start" {
      type = "Float64"
    }
    column "connect_end" {
      type = "Float64"
    }
    column "request_start" {
      type = "Float64"
    }
    column "response_start" {
      type = "Float64"
    }
    column "response_end" {
      type = "Float64"
    }
    column "decoded_body_size" {
      type = "Int64"
    }
    column "encoded_body_size" {
      type = "Int64"
    }
    column "initiator_type" {
      type = "LowCardinality(String)"
    }
    column "next_hop_protocol" {
      type = "LowCardinality(String)"
    }
    column "render_blocking_status" {
      type = "LowCardinality(String)"
    }
    column "response_status" {
      type = "Int64"
    }
    column "transfer_size" {
      type = "Int64"
    }
    column "largest_contentful_paint_element" {
      type = "String"
    }
    column "largest_contentful_paint_render_time" {
      type = "Float64"
    }
    column "largest_contentful_paint_load_time" {
      type = "Float64"
    }
    column "largest_contentful_paint_size" {
      type = "Float64"
    }
    column "largest_contentful_paint_id" {
      type = "String"
    }
    column "largest_contentful_paint_url" {
      type = "String"
    }
    column "dom_complete" {
      type = "Float64"
    }
    column "dom_content_loaded_event" {
      type = "Float64"
    }
    column "dom_interactive" {
      type = "Float64"
    }
    column "load_event_end" {
      type = "Float64"
    }
    column "load_event_start" {
      type = "Float64"
    }
    column "redirect_count" {
      type = "Int64"
    }
    column "navigation_type" {
      type = "LowCardinality(String)"
    }
    column "unload_event_end" {
      type = "Float64"
    }
    column "unload_event_start" {
      type = "Float64"
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
  materialized_view "person_distinct_id_mv" {
    to_table = "posthog.person_distinct_id"
    query    = file("sql/person_distinct_id_mv.sql")

    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    column "team_id" {
      type = "Int64"
    }
    column "_sign" {
      type = "Int16"
    }
    column "_timestamp" {
      type = "Nullable(DateTime)"
    }
    column "_offset" {
      type = "UInt64"
    }
  }
  materialized_view "person_overrides_mv" {
    to_table = "posthog.person_overrides"
    query    = file("sql/person_overrides_mv.sql")

    column "team_id" {
      type = "Int32"
    }
    column "old_person_id" {
      type = "UUID"
    }
    column "override_person_id" {
      type = "UUID"
    }
    column "merged_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "oldest_event" {
      type = "DateTime64(6, 'UTC')"
    }
    column "version" {
      type = "Int32"
    }
  }
  materialized_view "raw_sessions_mv" {
    to_table = "posthog.writable_raw_sessions"
    query    = file("sql/raw_sessions_mv.sql")

    column "team_id" {
      type = "Int64"
    }
    column "session_id_v7" {
      type = "UInt128"
    }
    column "distinct_id" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "min_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "max_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "max_inserted_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "urls" {
      type = "Array(String)"
    }
    column "entry_url" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "end_url" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "last_external_click_url" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "initial_browser" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_browser_version" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_os" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_os_version" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_device_type" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_viewport_width" {
      type = "AggregateFunction(argMin, Int64, DateTime64(6, 'UTC'))"
    }
    column "initial_viewport_height" {
      type = "AggregateFunction(argMin, Int64, DateTime64(6, 'UTC'))"
    }
    column "initial_geoip_country_code" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_geoip_subdivision_1_code" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_geoip_subdivision_1_name" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_geoip_subdivision_city_name" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_geoip_time_zone" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_referring_domain" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_source" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_campaign" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_medium" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_term" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_content" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gad_source" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gclsrc" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_dclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gbraid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_wbraid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_fbclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_msclkid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_twclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_li_fat_id" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_mc_cid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_igshid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_ttclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_epik" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_qclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_sccid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial__kx" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_irclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "pageview_count" {
      type = "UInt64"
    }
    column "pageview_uniq" {
      type = "AggregateFunction(uniq, Nullable(UUID))"
    }
    column "autocapture_count" {
      type = "UInt64"
    }
    column "autocapture_uniq" {
      type = "AggregateFunction(uniq, Nullable(UUID))"
    }
    column "screen_count" {
      type = "UInt64"
    }
    column "screen_uniq" {
      type = "AggregateFunction(uniq, Nullable(UUID))"
    }
    column "maybe_has_session_replay" {
      type = "Bool"
    }
    column "page_screen_autocapture_uniq_up_to" {
      type = "AggregateFunction(uniqUpTo(1), Nullable(UUID))"
    }
    column "vitals_lcp" {
      type = "AggregateFunction(argMin, Nullable(Float64), DateTime64(6, 'UTC'))"
    }
  }
  materialized_view "sessions_mv" {
    to_table = "posthog.writable_sessions"
    query    = file("sql/sessions_mv.sql")

    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "min_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "max_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "urls" {
      type = "Array(String)"
    }
    column "entry_url" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "exit_url" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "initial_referring_domain" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_source" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_campaign" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_medium" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_term" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_content" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gad_source" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gclsrc" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_dclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gbraid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_wbraid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_fbclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_msclkid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_twclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_li_fat_id" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_mc_cid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_igshid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_ttclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_epik" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_qclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_sccid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "event_count_map" {
      type = "Map(String, UInt64)"
    }
    column "pageview_count" {
      type = "UInt64"
    }
    column "autocapture_count" {
      type = "UInt64"
    }
  }
  dictionary "exchange_rate_dict" {
    primary_key = ["currency"]
    lifetime {
      min = 3000
      max = 3600
    }
    range {
      min = "start_date"
      max = "end_date"
    }
    attribute "currency" {
      type = "String"
    }
    attribute "start_date" {
      type = "Date"
    }
    attribute "end_date" {
      type = "Nullable(Date)"
    }
    attribute "rate" {
      type = "Decimal64(10)"
    }
    source "clickhouse" {
      user  = "default"
      query = "SELECT currency, date AS start_date, leadInFrame(date::Nullable(Date), 1, NULL::Nullable(Date)) OVER w AS end_date, argMax(rate, version) AS rate FROM `posthog`.`exchange_rate` GROUP BY date, currency WINDOW w AS ( PARTITION BY currency ORDER BY date ASC ROWS BETWEEN 1 FOLLOWING AND 1 FOLLOWING )"
    }
    layout "complex_key_range_hashed" {
      range_lookup_strategy = "max"
    }
  }
  dictionary "person_distinct_id_overrides_dict" {
    primary_key = ["team_id", "distinct_id"]
    lifetime {
      min = 3600
      max = 18000
    }
    attribute "team_id" {
      type = "Int64"
    }
    attribute "distinct_id" {
      type = "String"
    }
    attribute "person_id" {
      type = "UUID"
    }
    source "clickhouse" {
      user  = "default"
      query = "SELECT team_id, distinct_id, argMax(person_id, version) AS person_id FROM posthog.person_distinct_id_overrides GROUP BY team_id, distinct_id"
    }
    layout "complex_key_hashed" {
    }
  }
  dictionary "person_overrides_dict" {
    primary_key = ["team_id", "old_person_id"]
    lifetime {
      min = 5
      max = 10
    }
    attribute "team_id" {
      type = "INT"
    }
    attribute "old_person_id" {
      type = "UUID"
    }
    attribute "override_person_id" {
      type = "UUID"
    }
    source "clickhouse" {
      user  = "default"
      query = "\\nSELECT\\n    team_id,\\n    old_person_id,\\n    argMax(override_person_id, version)\\nFROM\\n    `posthog`.`person_overrides` AS overrides\\nGROUP BY\\n    team_id,\\n    old_person_id\\n"
    }
    layout "complex_key_hashed" {
      preallocate = 1
    }
  }
  patch_table "sharded_events" {
    modify_column "$group_0" {
      type         = "String"
      materialized = "replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), '^\"|\"$', '')"
      comment      = "column_materializer::$group_0"
    }
    modify_column "$group_1" {
      type         = "String"
      materialized = "replaceRegexpAll(JSONExtractRaw(properties, '$group_1'), '^\"|\"$', '')"
      comment      = "column_materializer::$group_1"
    }
    modify_column "$group_2" {
      type         = "String"
      materialized = "replaceRegexpAll(JSONExtractRaw(properties, '$group_2'), '^\"|\"$', '')"
      comment      = "column_materializer::$group_2"
    }
    modify_column "$group_3" {
      type         = "String"
      materialized = "replaceRegexpAll(JSONExtractRaw(properties, '$group_3'), '^\"|\"$', '')"
      comment      = "column_materializer::$group_3"
    }
    modify_column "$group_4" {
      type         = "String"
      materialized = "replaceRegexpAll(JSONExtractRaw(properties, '$group_4'), '^\"|\"$', '')"
      comment      = "column_materializer::$group_4"
    }
    modify_column "$window_id" {
      type         = "String"
      materialized = "replaceRegexpAll(JSONExtractRaw(properties, '$window_id'), '^\"|\"$', '')"
      comment      = "column_materializer::$window_id"
    }
    modify_column "$session_id" {
      type         = "String"
      materialized = "replaceRegexpAll(JSONExtractRaw(properties, '$session_id'), '^\"|\"$', '')"
      comment      = "column_materializer::$session_id"
    }
    modify_column "properties_group_custom" {
      type         = "Map(String, String)"
      materialized = "mapSort(mapFilter((key, _) -> ((key NOT LIKE '$%') AND (key NOT IN ('token', 'distinct_id', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'gad_source', 'gclsrc', 'dclid', 'gbraid', 'wbraid', 'fbclid', 'msclkid', 'twclid', 'li_fat_id', 'mc_cid', 'igshid', 'ttclid', 'rdt_cid', 'epik', 'qclid', 'sccid', 'irclid', '_kx'))), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))"
      codec        = "ZSTD(1)"
    }
    drop_columns = ["mat_historical_migration"]
    column "elements_chain" {
      type = "String"
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
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "mat_$ai_trace_id" {
      type         = "Nullable(String)"
      materialized = "JSONExtract(properties, '$ai_trace_id', 'Nullable(String)')"
    }
    drop_indexes = ["minmax_mat_historical_migration", "is_deleted_idx", "minmax_historical_migration"]
    index "minmax_$group_0" {
      expr        = "`$group_0`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$group_1" {
      expr        = "`$group_1`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$group_2" {
      expr        = "`$group_2`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$group_3" {
      expr        = "`$group_3`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$group_4" {
      expr        = "`$group_4`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$window_id" {
      expr        = "`$window_id`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$session_id" {
      expr        = "`$session_id`"
      type        = "minmax"
      granularity = 1
    }
    index "kafka_timestamp_minmax_sharded_events" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    index "is_deleted_idx" {
      expr        = "(is_deleted)"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_historical_migration" {
      expr        = "(historical_migration)"
      type        = "minmax"
      granularity = 1
    }
  }

  patch_table "events" {
    modify_column "properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    drop_columns = ["mat_historical_migration"]
    column "elements_chain" {
      type = "String"
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
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "mat_$ai_trace_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_trace_id"
    }
    column "mat_$ai_experiment_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_experiment_id"
    }
  }
  table "billing_usage_records" {
    column "schema_version" { type = "UInt8" }
    column "record_id" { type = "String" }
    column "producer_id" { type = "LowCardinality(String)" }
    column "team_id" { type = "Int64" }
    column "organization_id" { type = "UUID" }
    column "usage_key" { type = "LowCardinality(String)" }
    column "unit" { type = "LowCardinality(String)" }
    column "quantity" { type = "Int64" }
    column "timestamp" { type = "DateTime64(6, 'UTC')" }
    column "inserted_at" { type = "DateTime64(6, 'UTC')" }
    column "_timestamp" { type = "DateTime" }
    column "_offset" { type = "UInt64" }
    column "_partition" { type = "UInt64" }
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_billing_usage_records"
      sharding_key    = "cityHash64(team_id)"
    }
  }

  view "events_batch_export_backfill" {
    query = <<SQL
SELECT
  team_id AS team_id,
  timestamp AS timestamp,
  event AS event,
  distinct_id AS distinct_id,
  toString(uuid) AS uuid,
  timestamp AS _inserted_at,
  created_at AS created_at,
  elements_chain AS elements_chain,
  toString(person_id) AS person_id,
  nullIf(properties, '') AS properties,
  nullIf(person_properties, '') AS person_properties,
  nullIf(JSONExtractString(properties, '$set'), '') AS set,
  nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
FROM posthog.events
WHERE
  (team_id = {team_id: Int64})
AND
  (events.timestamp >= {interval_start: DateTime64})
AND
  (events.timestamp < {interval_end: DateTime64})
AND
  ((length({include_events: Array(String)}) = 0) OR (event IN ({include_events: Array(String)})))
AND
  ((length({exclude_events: Array(String)}) = 0) OR (event NOT IN ({exclude_events: Array(String)})))
ORDER BY _inserted_at ASC, event ASC
LIMIT 1 BY team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid)
SETTINGS
  optimize_aggregation_in_order = 1
SQL

  }

  view "persons_batch_export_backfill" {
    query = <<SQL
SELECT
  pd.team_id AS team_id,
  pd.distinct_id AS distinct_id,
  toString(p.id) AS person_id,
  p.properties AS properties,
  pd.version AS person_distinct_id_version,
  p.version AS person_version,
  p.created_at AS created_at,
  multiIf(
    (pd._timestamp < {interval_end: DateTime64})
    AND (NOT (p._timestamp < {interval_end: DateTime64})),
    pd._timestamp,
    (p._timestamp < {interval_end: DateTime64})
    AND (NOT (pd._timestamp < {interval_end: DateTime64})),
    p._timestamp,
    least(p._timestamp, pd._timestamp)
  ) AS _inserted_at
FROM
  (SELECT team_id, distinct_id, max(version) AS version, argMax(person_id, person_distinct_id2.version) AS person_id, argMax(_timestamp, person_distinct_id2.version) AS _timestamp FROM posthog.person_distinct_id2 PREWHERE team_id = {team_id: Int64} GROUP BY team_id, distinct_id) AS pd INNER JOIN (SELECT team_id, id, max(version) AS version, argMax(properties, person.version) AS properties, argMax(created_at, person.version) AS created_at, argMax(_timestamp, person.version) AS _timestamp FROM posthog.person PREWHERE team_id = {team_id: Int64} GROUP BY team_id, id) AS p ON (p.id = pd.person_id) AND (p.team_id = pd.team_id)
WHERE
  (pd.team_id = {team_id: Int64})
AND
  (p.team_id = {team_id: Int64})
AND
  ((pd._timestamp < {interval_end: DateTime64}) OR (p._timestamp < {interval_end: DateTime64}))
ORDER BY _inserted_at ASC
SQL

  }

  table "app_metrics" {
    column "team_id" {
      type = "Int64"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "plugin_config_id" {
      type = "Int64"
    }
    column "category" {
      type = "LowCardinality(String)"
    }
    column "job_id" {
      type = "String"
    }
    column "successes" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "successes_on_retry" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "failures" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "error_uuid" {
      type = "UUID"
    }
    column "error_type" {
      type = "String"
    }
    column "error_details" {
      type  = "String"
      codec = "ZSTD(3)"
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
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_app_metrics"
      sharding_key    = "rand()"
    }
  }

  table "precalculated_events" {
    column "team_id" {
      type = "Int64"
    }
    column "date" {
      type = "Date"
    }
    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    column "condition" {
      type = "String"
    }
    column "uuid" {
      type = "UUID"
    }
    column "source" {
      type = "String"
    }
    column "_timestamp" {
      type = "DateTime64(6)"
    }
    column "_partition" {
      type = "UInt64"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_precalculated_events"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }

  table "precalculated_person_properties" {
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    column "condition" {
      type = "String"
    }
    column "matches" {
      type = "Bool"
    }
    column "source" {
      type = "String"
    }
    column "_timestamp" {
      type = "DateTime64(6)"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_precalculated_person_properties"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }

  table "sharded_app_metrics" {
    order_by     = ["team_id", "plugin_config_id", "job_id", "category", "toStartOfHour(timestamp)", "error_type", "error_uuid"]
    partition_by = "toYYYYMM(timestamp)"
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int64"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "plugin_config_id" {
      type = "Int64"
    }
    column "category" {
      type = "LowCardinality(String)"
    }
    column "job_id" {
      type = "String"
    }
    column "successes" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "successes_on_retry" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "failures" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "error_uuid" {
      type = "UUID"
    }
    column "error_type" {
      type = "String"
    }
    column "error_details" {
      type  = "String"
      codec = "ZSTD(3)"
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
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.sharded_app_metrics"
      replica_name = "{replica}"
    }
  }

  table "sharded_precalculated_events" {
    order_by     = ["team_id", "condition", "date", "distinct_id", "uuid"]
    partition_by = "toYYYYMM(date)"
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int64"
    }
    column "date" {
      type = "Date"
    }
    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    column "condition" {
      type = "String"
    }
    column "uuid" {
      type = "UUID"
    }
    column "source" {
      type = "String"
    }
    column "_timestamp" {
      type = "DateTime64(6)"
    }
    column "_partition" {
      type = "UInt64"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.sharded_precalculated_events"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }

  table "sharded_precalculated_person_properties" {
    order_by = ["team_id", "condition", "distinct_id"]
    settings = {
      index_granularity = "8192"
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
    column "condition" {
      type = "String"
    }
    column "matches" {
      type = "Bool"
    }
    column "source" {
      type = "String"
    }
    column "_timestamp" {
      type = "DateTime64(6)"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.sharded_precalculated_person_properties"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }

  table "sharded_raw_sessions" {
    order_by     = ["team_id", "toStartOfHour(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000)))", "cityHash64(session_id_v7)", "session_id_v7"]
    partition_by = "toYYYYMM(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000)))"
    sample_by    = "cityHash64(session_id_v7)"
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int64"
    }
    column "session_id_v7" {
      type = "UInt128"
    }
    column "distinct_id" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "min_timestamp" {
      type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "max_inserted_at" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "urls" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "entry_url" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "end_url" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "last_external_click_url" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "initial_browser" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_browser_version" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_os" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_os_version" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_device_type" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_viewport_width" {
      type = "AggregateFunction(argMin, Int64, DateTime64(6, 'UTC'))"
    }
    column "initial_viewport_height" {
      type = "AggregateFunction(argMin, Int64, DateTime64(6, 'UTC'))"
    }
    column "initial_geoip_country_code" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_geoip_subdivision_1_code" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_geoip_subdivision_1_name" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_geoip_subdivision_city_name" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_geoip_time_zone" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_referring_domain" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_source" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_campaign" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_medium" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_term" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_content" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gad_source" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gclsrc" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_dclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gbraid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_wbraid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_fbclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_msclkid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_twclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_li_fat_id" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_mc_cid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_igshid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_ttclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_epik" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_qclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_sccid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial__kx" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_irclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "pageview_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "pageview_uniq" {
      type = "AggregateFunction(uniq, Nullable(UUID))"
    }
    column "autocapture_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "autocapture_uniq" {
      type = "AggregateFunction(uniq, Nullable(UUID))"
    }
    column "screen_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "screen_uniq" {
      type = "AggregateFunction(uniq, Nullable(UUID))"
    }
    column "maybe_has_session_replay" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "page_screen_autocapture_uniq_up_to" {
      type = "AggregateFunction(uniqUpTo(1), Nullable(UUID))"
    }
    column "vitals_lcp" {
      type = "AggregateFunction(argMin, Nullable(Float64), DateTime64(6, 'UTC'))"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.raw_sessions"
      replica_name = "{replica}"
    }
  }

  table "sharded_sessions" {
    order_by     = ["toStartOfDay(min_timestamp)", "team_id", "session_id"]
    partition_by = "toYYYYMM(min_timestamp)"
    settings = {
      index_granularity = "512"
    }
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "SimpleAggregateFunction(any, String)"
    }
    column "min_timestamp" {
      type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "urls" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "entry_url" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "exit_url" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "initial_referring_domain" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_source" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_campaign" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_medium" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_term" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_content" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gad_source" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gclsrc" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_dclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gbraid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_wbraid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_fbclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_msclkid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_twclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_li_fat_id" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_mc_cid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_igshid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_ttclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_epik" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_qclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_sccid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "event_count_map" {
      type = "SimpleAggregateFunction(sumMap, Map(String, Int64))"
    }
    column "pageview_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "autocapture_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.sessions"
      replica_name = "{replica}"
    }
  }

  table "writable_events" {
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
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_events"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }

  table "web_pre_aggregated_bounces_staging" {
    order_by     = ["team_id", "period_bucket", "host", "device_type", "entry_pathname", "end_pathname", "browser", "os", "viewport_width", "viewport_height", "referring_domain", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "country_code", "city_name", "region_code", "region_name", "has_gclid", "has_gad_source_paid_search", "has_fbclid", "mat_metadata_loggedIn", "mat_metadata_backend"]
    partition_by = "toYYYYMMDD(period_bucket)"
    settings = {
      index_granularity = "8192"
    }
    column "period_bucket" {
      type = "DateTime"
    }
    column "team_id" {
      type = "UInt64"
    }
    column "host" {
      type = "String"
    }
    column "device_type" {
      type = "String"
    }
    column "entry_pathname" {
      type = "String"
    }
    column "end_pathname" {
      type = "String"
    }
    column "browser" {
      type = "String"
    }
    column "os" {
      type = "String"
    }
    column "viewport_width" {
      type = "Int64"
    }
    column "viewport_height" {
      type = "Int64"
    }
    column "referring_domain" {
      type = "String"
    }
    column "utm_source" {
      type = "String"
    }
    column "utm_medium" {
      type = "String"
    }
    column "utm_campaign" {
      type = "String"
    }
    column "utm_term" {
      type = "String"
    }
    column "utm_content" {
      type = "String"
    }
    column "country_code" {
      type = "String"
    }
    column "city_name" {
      type = "String"
    }
    column "region_code" {
      type = "String"
    }
    column "region_name" {
      type = "String"
    }
    column "has_gclid" {
      type = "Bool"
    }
    column "has_gad_source_paid_search" {
      type = "Bool"
    }
    column "has_fbclid" {
      type = "Bool"
    }
    column "mat_metadata_loggedIn" {
      type = "Bool"
    }
    column "mat_metadata_backend" {
      type = "String"
    }
    column "persons_uniq_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sessions_uniq_state" {
      type = "AggregateFunction(uniq, String)"
    }
    column "pageviews_count_state" {
      type = "AggregateFunction(sum, UInt64)"
    }
    column "bounces_count_state" {
      type = "AggregateFunction(sum, UInt64)"
    }
    column "total_session_duration_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "total_session_count_state" {
      type = "AggregateFunction(sum, UInt64)"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.web_pre_aggregated_bounces_staging"
      replica_name = "{replica}-{shard}"
    }
  }

  table "web_pre_aggregated_stats_staging" {
    order_by     = ["team_id", "period_bucket", "host", "device_type", "pathname", "entry_pathname", "end_pathname", "browser", "os", "viewport_width", "viewport_height", "referring_domain", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "country_code", "city_name", "region_code", "region_name", "has_gclid", "has_gad_source_paid_search", "has_fbclid", "mat_metadata_loggedIn", "mat_metadata_backend"]
    partition_by = "toYYYYMMDD(period_bucket)"
    settings = {
      index_granularity = "8192"
    }
    column "period_bucket" {
      type = "DateTime"
    }
    column "team_id" {
      type = "UInt64"
    }
    column "host" {
      type = "String"
    }
    column "device_type" {
      type = "String"
    }
    column "pathname" {
      type = "String"
    }
    column "entry_pathname" {
      type = "String"
    }
    column "end_pathname" {
      type = "String"
    }
    column "browser" {
      type = "String"
    }
    column "os" {
      type = "String"
    }
    column "viewport_width" {
      type = "Int64"
    }
    column "viewport_height" {
      type = "Int64"
    }
    column "referring_domain" {
      type = "String"
    }
    column "utm_source" {
      type = "String"
    }
    column "utm_medium" {
      type = "String"
    }
    column "utm_campaign" {
      type = "String"
    }
    column "utm_term" {
      type = "String"
    }
    column "utm_content" {
      type = "String"
    }
    column "country_code" {
      type = "String"
    }
    column "city_name" {
      type = "String"
    }
    column "region_code" {
      type = "String"
    }
    column "region_name" {
      type = "String"
    }
    column "has_gclid" {
      type = "Bool"
    }
    column "has_gad_source_paid_search" {
      type = "Bool"
    }
    column "has_fbclid" {
      type = "Bool"
    }
    column "mat_metadata_loggedIn" {
      type = "Bool"
    }
    column "mat_metadata_backend" {
      type = "String"
    }
    column "persons_uniq_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sessions_uniq_state" {
      type = "AggregateFunction(uniq, String)"
    }
    column "pageviews_count_state" {
      type = "AggregateFunction(sum, UInt64)"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.web_pre_aggregated_stats_staging"
      replica_name = "{replica}-{shard}"
    }
  }
}
