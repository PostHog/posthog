database "posthog" {
  table "writable_events_json" {
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "JSON(max_dynamic_paths = 0, `$agent_application_id` String, `$agent_revision_id` String, `$agent_session_id` String, `$agent_turn` String, `$ai_audio_cost_usd` String, `$ai_audio_input_tokens` String, `$ai_audio_output_tokens` String, `$ai_batch_run_id` String, `$ai_cache_creation_input_tokens` String, `$ai_cache_read_input_tokens` String, `$ai_error` String, `$ai_error_normalized` String, `$ai_error_type` String, `$ai_evaluation_allows_na` String, `$ai_evaluation_applicable` String, `$ai_evaluation_id` String, `$ai_evaluation_name` String, `$ai_evaluation_reasoning` String, `$ai_evaluation_result` String, `$ai_evaluation_result_type` String, `$ai_evaluation_runtime` String, `$ai_evaluation_skipped` String, `$ai_evaluation_start_time` String, `$ai_evaluation_type` String, `$ai_experiment_id` String, `$ai_framework` String, `$ai_generation_id` String, `$ai_http_status` String, `$ai_image_cost_usd` String, `$ai_image_input_tokens` String, `$ai_image_output_tokens` String, `$ai_input_cost_usd` String, `$ai_input_tokens` String, `$ai_is_error` String, `$ai_latency` String, `$ai_model` String, `$ai_output_cost_usd` String, `$ai_output_tokens` String, `$ai_parent_id` String, `$ai_prompt_name` String, `$ai_provider` String, `$ai_reasoning_tokens` String, `$ai_request_cost_usd` String, `$ai_session_id` String, `$ai_span_name` String, `$ai_span_type` String, `$ai_span_id` String, `$ai_sentiment_label` String, `$ai_sentiment_message_count` String, `$ai_sentiment_score` String, `$ai_target_event_id` String, `$ai_text_input_tokens` String, `$ai_text_output_tokens` String, `$ai_time_to_first_token` String, `$ai_total_cost_usd` String, `$ai_total_tokens` String, `$ai_tools_called` String, `$ai_trace_id` String, `$ai_trace_name` String, `$ai_video_cost_usd` String, `$ai_video_input_tokens` String, `$ai_video_output_tokens` String, `$ai_web_search_cost_usd` String, `$ai_web_search_count` String, `$ai_origin` String, `$anon_distinct_id` String, `$app_build` String, `$app_name` String, `$app_namespace` String, `$app_version` String, `$browser` String, `$browser_language` String, `$browser_language_prefix` String, `$browser_type` String, `$browser_version` String, `$current_url` String, `$device` String, `$device_id` String, `$device_model` String, `$device_manufacturer` String, `$device_name` String, `$device_type` String, `$el_text` String, `$event_type` String, `$exception_fingerprint` String, `$exception_functions` Array(String), `$exception_handled` String, `$exception_is_synthetic` String, `$exception_issue_id` String, `$exception_level` String, `$exception_list` Array(JSON(max_dynamic_paths = 0, type String, value String)), `$exception_message` String, `$exception_proposed_fingerprint` String, `$exception_sources` Array(String), `$exception_type` String, `$exception_types` Array(String), `$exception_values` Array(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_postal_code` String, `$geoip_subdivision_1_name` String, `$geoip_subdivision_2_code` String, `$geoip_subdivision_2_name` String, `$geoip_time_zone` LowCardinality(String), `$geoip_subdivision_1_code` String, `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$groups.organization` String, `$groups.project` String, `$groups.instance` String, `$group_set.icp_company_type` String, `$host` String, `$initial_pathname` String, `$initial_referrer` String, `$initial_referring_domain` String, `$client_session_initial_pathname` String, `$client_session_initial_referring_host` String, `$client_session_initial_utm_campaign` String, `$client_session_initial_utm_content` String, `$client_session_initial_utm_medium` String, `$client_session_initial_utm_source` String, `$client_session_initial_utm_term` String, `$initial_search_engine` String, `$ip` String, `$is_identified` String, `$lib` String, `$lib_custom_api_host` String, `$lib_version` String, `$lib_version__minor` String, `$mcp_client_name` String, `$mcp_client_user_agent` String, `$mcp_duration_ms` String, `$mcp_error_message` String, `$mcp_exec_tool_call_description` String, `$mcp_exec_tool_call_name` String, `$mcp_intent` String, `$mcp_intent_source` String, `$mcp_is_error` String, `$mcp_listed_tool_names` Array(String), `$mcp_oauth_client_name` String, `$mcp_organization_id` String, `$mcp_project_id` String, `$mcp_session_id` String, `$mcp_source` String, `$mcp_tool_category` String, `$mcp_tool_description` String, `$mcp_tool_name` String, `$os` String, `$os_name` String, `$os_version` String, `$pathname` String, `$prev_pageview_max_content_percentage` String, `$prev_pageview_max_scroll_percentage` String, `$prev_pageview_pathname` String, `$process_person_profile` String, `$recording_status` String, `$referrer` String, `$referring_domain` String, `$replay_minimum_duration` String, `$replay_sample_rate` String, `$raw_user_agent` String, `$search_engine` String, `$screen_height` String, `$screen_name` String, `$screen_width` String, `$sent_at` String, `$session_id` String, `$session_entry_host` String, `$session_entry_pathname` String, `$session_entry_referrer` String, `$session_entry_referring_domain` String, `$session_entry_search_engine` String, `$session_entry_url` String, `$session_entry_utm_campaign` String, `$session_entry_utm_content` String, `$session_entry_utm_medium` String, `$session_entry_utm_source` String, `$session_entry_utm_term` String, `$session_recording_event_trigger_activated_session` String, `$session_recording_start_reason` String, `$session_recording_url_trigger_status` String, `$sdk_debug_recording_script_not_loaded` String, `$survey_id` String, `$survey_completed` String, `$survey_iteration` String, `$survey_iteration_start_date` String, `$survey_name` String, `$survey_partially_completed` String, `$survey_response` String, `$survey_response_1` String, `$survey_submission_id` String, `$time` String, `$timezone` String, `$timezone_offset` String, `$user_id` String, `$viewport_height` String, `$viewport_width` String, `$web_vitals_CLS_value` String, `$web_vitals_FCP_value` String, `$web_vitals_INP_value` String, `$web_vitals_LCP_value` String, `$window_id` String, `Account.client_id` String, `Connection.app.name` String, `Event.productCode` String, `HTTP Method` String, `Plan type and filter` String, `Subscription.plan.amount` String, `action` String, `action_name` String, `address` String, `apiErrorMessage` String, `apiName` String, `app_name` String, `app_version` String, `arguments` String, `audio_duration` String, `authentication_method` String, `auto_chapters` String, `auto_highlights` String, `category` String, `chain` String, `channel` String, `client_id` String, `client_name` String, `commit_sha` String, `community_id` String, `conceptName` String, `content_length` String, `content_safety` String, `context` String, `contributionError` String, `created_at` String, `created_by` String, `created_by_system` String, `currentScreen` String, `current_member_guid` String, `customer_email` String, `deal_id` String, `device_type` String, `disable_institution_search` String, `disfluencies` String, `distinct_id` String, `dual_channel` String, `duration` String, `email` String, `email_domain` String, `_kx` String, `dclid` String, `epik` String, `entity_detection` String, `env` String, `environment` String, `event` String, `event_count_in_month` String, `event_count_in_period` String, `events_projected_amount` String, `fbclid` String, `filter_profanity` String, `filters_count` String, `function` String, `gad_source` String, `gbraid` String, `gclid` String, `gclsrc` String, `gross` String, `group_id` String, `historical_migration` String, `iab_categories` String, `id` String, `index` String, `initial_dclid` String, `initial_fbclid` String, `initial_gclsrc` String, `initial__kx` String, `initial_epik` String, `initial_gad_source` String, `initial_gbraid` String, `initial_gclid` String, `initial_irclid` String, `initial_igshid` String, `initial_li_fat_id` String, `initial_mc_cid` String, `initial_msclkid` String, `initial_qclid` String, `initial_rdt_cid` String, `initial_sccid` String, `initial_utm_campaign` String, `initial_utm_content` String, `initial_utm_medium` String, `initial_utm_source` String, `initial_utm_term` String, `initial_step` String, `initial_ttclid` String, `initial_twclid` String, `initial_wbraid` String, `initiator` String, `insight` String, `institution_name` String, `inviteCode` String, `is_demo_project` String, `is_first_component_load` String, `is_first_event_for_user` String, `is_initial_aggregation` String, `is_oauth` String, `is_organization_first_user` String, `is_test_user` String, `item_count` String, `job_type` String, `key` String, `kind` String, `language_detection` String, `machine_id` String, `message` String, `method` String, `mode` String, `most_recent_app_os` String, `msclkid` String, `mc_cid` String, `igshid` String, `irclid` String, `li_fat_id` String, `qclid` String, `rdt_cid` String, `sccid` String, `ttclid` String, `twclid` String, `name` String, `nativeBuildVersion` String, `numberOfSecrets` String, `orderId` String, `orderType` String, `organization` String, `organization_id` String, `organization_name` String, `organizations` String, `origin` String, `osName` String, `owner_type` String, `page` String, `payment_status` String, `phone` String, `platform` String, `product` String, `product_analytics_projected_amount` String, `product_key` String, `progress` String, `protocol` String, `query` String, `ramp` String, `realm` String, `record-id` String, `recording_count_in_period` String, `recordings_projected_amount` String, `redact_pii` String, `referrer` String, `referrer_id` String, `region` String, `revenue` String, `screen_name` String, `sdk` String, `search_term` String, `sentiment_analysis` String, `session_replay_projected_amount` String, `sku` String, `source` String, `speaker_labels` String, `statusCode` String, `status_message` String, `store_url` String, `stripe_amount_paid` String, `subdomain` String, `subscriptionStatus` String, `summarization` String, `surface_tag` String, `survey_responses_count_in_period` String, `symbol` String, `tag` String, `target` String, `team` String, `testSessionId` String, `thread_id` String, `ticketId` String, `title` String, `token` String, `total_event_actions_count` String, `total_usd` String, `type` String, `url` String, `url_promotion_id` String, `usd` String, `user_agent` String, `user_email_domain` String, `user_platform` String, `utm_campaign` String, `utm_content` String, `utm_medium` String, `utm_source` String, `utm_term` String, `valid_ach_accounts` String, `wbraid` String, `wlo_enabled` String, `workplace_billing_plan` String, `workspace` String, `workspaceId` String)"
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
      type = "JSON(max_dynamic_paths = 0, `$app_version` String, `$app_build` String, `$app_name` String, `$app_namespace` String, `$browser` String, `$browser_language` String, `$browser_language_prefix` String, `$browser_type` String, `$browser_version` String, `$current_url` String, `$device` String, `$device_id` String, `$device_manufacturer` String, `$device_model` String, `$device_name` String, `$device_type` String, `$geoip_continent_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_city_name` LowCardinality(String), `$geoip_postal_code` String, `$geoip_subdivision_1_code` String, `$geoip_subdivision_1_name` String, `$geoip_subdivision_2_code` String, `$geoip_subdivision_2_name` String, `$geoip_time_zone` LowCardinality(String), `$initial_current_url` String, `$initial_app_build` String, `$initial_app_name` String, `$initial_app_namespace` String, `$initial_app_version` String, `$initial_browser` String, `$initial_browser_language` String, `$initial_browser_language_prefix` String, `$initial_browser_type` String, `$initial_browser_version` String, `$initial_device` String, `$initial_device_id` String, `$initial_device_manufacturer` String, `$initial_device_model` String, `$initial_device_name` String, `$initial_device_type` String, `$initial_geoip_city_name` String, `$initial_geoip_continent_code` String, `$initial_geoip_continent_name` String, `$initial_geoip_country_code` String, `$initial_geoip_country_name` String, `$initial_geoip_postal_code` String, `$initial_geoip_subdivision_1_code` String, `$initial_geoip_subdivision_1_name` String, `$initial_geoip_subdivision_2_code` String, `$initial_geoip_subdivision_2_name` String, `$initial_geoip_time_zone` String, `$initial_fbclid` String, `$initial_gad_source` String, `$initial_gbraid` String, `$initial_gclid` String, `$initial_gclsrc` String, `$initial_dclid` String, `$initial_msclkid` String, `$initial_twclid` String, `$initial_li_fat_id` String, `$initial_mc_cid` String, `$initial_igshid` String, `$initial_ttclid` String, `$initial_rdt_cid` String, `$initial_epik` String, `$initial_qclid` String, `$initial_sccid` String, `$initial_irclid` String, `$initial__kx` String, `$initial_pathname` String, `$initial_os` String, `$initial_os_name` String, `$initial_os_version` String, `$initial_raw_user_agent` String, `$initial_referrer` String, `$initial_referring_domain` String, `$initial_screen_height` String, `$initial_screen_width` String, `$initial_search_engine` String, `$initial_utm_campaign` String, `$initial_utm_content` String, `$initial_utm_medium` String, `$initial_utm_source` String, `$initial_utm_term` String, `$initial_viewport_height` String, `$initial_viewport_width` String, `$initial_wbraid` String, `$os_name` String, `$os` String, `$os_version` String, `$pathname` String, `$raw_user_agent` String, `$referrer` String, `$screen_height` String, `$screen_width` String, `$search_engine` String, `$viewport_height` String, `$viewport_width` String, `$referring_domain` String, `$email` String, `$last_seen_survey_date` String, `$organization_id` String, `$product_tour_last_seen_date` String, `$survey_last_seen_date` String, `Email Domain` String, `companyName` String, `customer` String, `email` String, `first_name` String, `hubspot_score` String, `id` String, `icp_role` String, `is_email_verified` String, `is_signed_up` String, `last_name` String, `name` String, `organization_id` String, `organization_member_count` String, `role` String, `role_at_organization` String, `serverMarketing` String, `serverMasterclass` String, `user_email_domain` String, `username` String, `utm_source` String, `utm_medium` String, `utm_campaign` String, `utm_content` String, `utm_term` String, `gclid` String, `gad_source` String, `gclsrc` String, `dclid` String, `gbraid` String, `wbraid` String, `fbclid` String, `msclkid` String, `twclid` String, `li_fat_id` String, `mc_cid` String, `igshid` String, `ttclid` String, `rdt_cid` String, `epik` String, `qclid` String, `sccid` String, `irclid` String, `_kx` String, `val_region` String)"
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
}
