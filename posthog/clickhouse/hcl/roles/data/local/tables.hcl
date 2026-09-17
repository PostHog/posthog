database "posthog" {
  table "events_json" {
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "JSON(max_dynamic_types=8, max_dynamic_paths=256, `$active_feature_flags` Array(String), `$ai_experiment_id` Nullable(String), `$ai_http_status` Nullable(String), `$ai_is_error` Nullable(String), `$ai_model` Nullable(String), `$ai_parent_id` Nullable(String), `$ai_prompt_name` Nullable(String), `$ai_provider` Nullable(String), `$ai_session_id` Nullable(String), `$ai_span_id` Nullable(String), `$ai_total_cost_usd` Nullable(String), `$ai_trace_id` Nullable(String), `$anon_distinct_id` Nullable(String), `$app_build` Nullable(String), `$app_namespace` Nullable(String), `$app_version` Nullable(String), `$browser` Nullable(String), `$browser_version` Nullable(String), `$current_url` Nullable(String), `$device` Nullable(String), `$device_id` Nullable(String), `$device_model` Nullable(String), `$device_type` Nullable(String), `$el_text` Nullable(String), `$event_type` Nullable(String), `$exception_fingerprint` Nullable(String), `$exception_functions` Array(String), `$exception_issue_id` Nullable(String), `$exception_sources` Array(String), `$exception_types` Array(String), `$exception_values` Array(String), `$feature_flag` Nullable(String), `$feature_flag_payloads` Nullable(String), `$feature_flag_response` Nullable(String), `$geoip_city_name` Nullable(String), `$geoip_country_code` Nullable(String), `$geoip_country_name` Nullable(String), `$geoip_subdivision_1_code` Nullable(String), `$group_0` Nullable(String), `$group_1` Nullable(String), `$group_2` Nullable(String), `$group_3` Nullable(String), `$group_4` Nullable(String), `$groups` Nullable(String), `$host` Nullable(String), `$initial_pathname` Nullable(String), `$initial_referrer` Nullable(String), `$initial_referring_domain` Nullable(String), `$ip` Nullable(String), `$is_identified` Nullable(String), `$lib` Nullable(String), `$lib_custom_api_host` Nullable(String), `$lib_version` Nullable(String), `$lib_version__minor` Nullable(String), `$os` Nullable(String), `$os_name` Nullable(String), `$os_version` Nullable(String), `$pathname` Nullable(String), `$prev_pageview_max_content_percentage` Nullable(String), `$prev_pageview_max_scroll_percentage` Nullable(String), `$prev_pageview_pathname` Nullable(String), `$process_person_profile` Nullable(String), `$referrer` Nullable(String), `$referring_domain` Nullable(String), `$screen_height` Nullable(String), `$screen_name` Nullable(String), `$screen_width` Nullable(String), `$sent_at` Nullable(String), `$session_id` Nullable(String), `$survey_id` Nullable(String), `$survey_response` Nullable(String), `$survey_response_1` Nullable(String), `$time` Nullable(String), `$user_id` Nullable(String), `$viewport_height` Nullable(String), `$viewport_width` Nullable(String), `$web_vitals_CLS_value` Nullable(String), `$web_vitals_FCP_value` Nullable(String), `$web_vitals_INP_value` Nullable(String), `$web_vitals_LCP_value` Nullable(String), `$window_id` Nullable(String))"
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
      default = "''"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
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
      type = "JSON(max_dynamic_types=6, max_dynamic_paths=32, `$app_version` Nullable(String), `$browser` Nullable(String), `$current_url` Nullable(String), `$geoip_continent_name` Nullable(String), `$geoip_country_code` Nullable(String), `$geoip_country_name` Nullable(String), `$initial_current_url` Nullable(String), `$initial_fbclid` Nullable(String), `$initial_gad_source` Nullable(String), `$initial_gbraid` Nullable(String), `$initial_gclid` Nullable(String), `$initial_msclkid` Nullable(String), `$initial_pathname` Nullable(String), `$initial_referring_domain` Nullable(String), `$initial_utm_campaign` Nullable(String), `$initial_utm_content` Nullable(String), `$initial_utm_medium` Nullable(String), `$initial_utm_source` Nullable(String), `$initial_utm_term` Nullable(String), `$initial_wbraid` Nullable(String), `$os_name` Nullable(String), `$referring_domain` Nullable(String))"
    }
    column "group0_properties" {
      type = "String"
      codec = "ZSTD(3)"
    }
    column "group1_properties" {
      type = "String"
      codec = "ZSTD(3)"
    }
    column "group2_properties" {
      type = "String"
      codec = "ZSTD(3)"
    }
    column "group3_properties" {
      type = "String"
      codec = "ZSTD(3)"
    }
    column "group4_properties" {
      type = "String"
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
      type = "Nullable(DateTime64(6, 'UTC'))"
      default = "now64()"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "is_deleted" {
      type = "Bool"
      default = "false"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
    column "historical_migration" {
      type = "Bool"
      default = "false"
    }
    column "$group_0" {
      type = "String"
    }
    column "$group_1" {
      type = "String"
    }
    column "$group_2" {
      type = "String"
    }
    column "$group_3" {
      type = "String"
    }
    column "$group_4" {
      type = "String"
    }
    column "$window_id" {
      type = "String"
    }
    column "$session_id" {
      type = "String"
    }
    column "$session_id_uuid" {
      type = "Nullable(UInt128)"
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_events_json"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }
  table "sharded_events_json" {
    order_by     = ["team_id", "toDate(timestamp)", "event", "timestamp", "cityHash64(distinct_id)", "distinct_id", "uuid"]
    partition_by = "toYYYYMM(timestamp)"
    primary_key  = ["team_id", "toDate(timestamp)", "event", "timestamp", "cityHash64(distinct_id)"]
    sample_by    = "cityHash64(distinct_id)"
    settings = {
      index_granularity                                             = "8192"
      merge_max_block_size                                          = "131072"
      merge_max_block_size_bytes                                    = "67108864"
      object_serialization_version                                  = "v3"
      object_shared_data_serialization_version                      = "map_with_buckets"
      object_shared_data_serialization_version_for_zero_level_parts = "map"
      vertical_merge_algorithm_min_rows_to_activate                 = "0"
    }
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "JSON(max_dynamic_types=8, max_dynamic_paths=256, `$active_feature_flags` Array(String), `$ai_experiment_id` Nullable(String), `$ai_http_status` Nullable(String), `$ai_is_error` Nullable(String), `$ai_model` Nullable(String), `$ai_parent_id` Nullable(String), `$ai_prompt_name` Nullable(String), `$ai_provider` Nullable(String), `$ai_session_id` Nullable(String), `$ai_span_id` Nullable(String), `$ai_total_cost_usd` Nullable(String), `$ai_trace_id` Nullable(String), `$anon_distinct_id` Nullable(String), `$app_build` Nullable(String), `$app_namespace` Nullable(String), `$app_version` Nullable(String), `$browser` Nullable(String), `$browser_version` Nullable(String), `$current_url` Nullable(String), `$device` Nullable(String), `$device_id` Nullable(String), `$device_model` Nullable(String), `$device_type` Nullable(String), `$el_text` Nullable(String), `$event_type` Nullable(String), `$exception_fingerprint` Nullable(String), `$exception_functions` Array(String), `$exception_issue_id` Nullable(String), `$exception_sources` Array(String), `$exception_types` Array(String), `$exception_values` Array(String), `$feature_flag` Nullable(String), `$feature_flag_payloads` Nullable(String), `$feature_flag_response` Nullable(String), `$geoip_city_name` Nullable(String), `$geoip_country_code` Nullable(String), `$geoip_country_name` Nullable(String), `$geoip_subdivision_1_code` Nullable(String), `$group_0` Nullable(String), `$group_1` Nullable(String), `$group_2` Nullable(String), `$group_3` Nullable(String), `$group_4` Nullable(String), `$groups` Nullable(String), `$host` Nullable(String), `$initial_pathname` Nullable(String), `$initial_referrer` Nullable(String), `$initial_referring_domain` Nullable(String), `$ip` Nullable(String), `$is_identified` Nullable(String), `$lib` Nullable(String), `$lib_custom_api_host` Nullable(String), `$lib_version` Nullable(String), `$lib_version__minor` Nullable(String), `$os` Nullable(String), `$os_name` Nullable(String), `$os_version` Nullable(String), `$pathname` Nullable(String), `$prev_pageview_max_content_percentage` Nullable(String), `$prev_pageview_max_scroll_percentage` Nullable(String), `$prev_pageview_pathname` Nullable(String), `$process_person_profile` Nullable(String), `$referrer` Nullable(String), `$referring_domain` Nullable(String), `$screen_height` Nullable(String), `$screen_name` Nullable(String), `$screen_width` Nullable(String), `$sent_at` Nullable(String), `$session_id` Nullable(String), `$survey_id` Nullable(String), `$survey_response` Nullable(String), `$survey_response_1` Nullable(String), `$time` Nullable(String), `$user_id` Nullable(String), `$viewport_height` Nullable(String), `$viewport_width` Nullable(String), `$web_vitals_CLS_value` Nullable(String), `$web_vitals_FCP_value` Nullable(String), `$web_vitals_INP_value` Nullable(String), `$web_vitals_LCP_value` Nullable(String), `$window_id` Nullable(String))"
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
      default = "''"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
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
      type = "JSON(max_dynamic_types=6, max_dynamic_paths=32, `$app_version` Nullable(String), `$browser` Nullable(String), `$current_url` Nullable(String), `$geoip_continent_name` Nullable(String), `$geoip_country_code` Nullable(String), `$geoip_country_name` Nullable(String), `$initial_current_url` Nullable(String), `$initial_fbclid` Nullable(String), `$initial_gad_source` Nullable(String), `$initial_gbraid` Nullable(String), `$initial_gclid` Nullable(String), `$initial_msclkid` Nullable(String), `$initial_pathname` Nullable(String), `$initial_referring_domain` Nullable(String), `$initial_utm_campaign` Nullable(String), `$initial_utm_content` Nullable(String), `$initial_utm_medium` Nullable(String), `$initial_utm_source` Nullable(String), `$initial_utm_term` Nullable(String), `$initial_wbraid` Nullable(String), `$os_name` Nullable(String), `$referring_domain` Nullable(String))"
    }
    column "group0_properties" {
      type = "String"
      codec = "ZSTD(3)"
    }
    column "group1_properties" {
      type = "String"
      codec = "ZSTD(3)"
    }
    column "group2_properties" {
      type = "String"
      codec = "ZSTD(3)"
    }
    column "group3_properties" {
      type = "String"
      codec = "ZSTD(3)"
    }
    column "group4_properties" {
      type = "String"
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
      type = "Nullable(DateTime64(6, 'UTC'))"
      default = "now64()"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "is_deleted" {
      type = "Bool"
      default = "false"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
    column "historical_migration" {
      type = "Bool"
      default = "false"
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
    index "kafka_timestamp_minmax_sharded_events" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    index "minmax_$group_0" {
      expr        = "properties.`$group_0`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$group_1" {
      expr        = "properties.`$group_1`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$group_2" {
      expr        = "properties.`$group_2`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$group_3" {
      expr        = "properties.`$group_3`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$group_4" {
      expr        = "properties.`$group_4`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$window_id" {
      expr        = "properties.`$window_id`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$session_id" {
      expr        = "properties.`$session_id`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$sent_at" {
      expr        = "properties.`$sent_at`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$initial_pathname" {
      expr        = "properties.`$initial_pathname`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$lib_version" {
      expr        = "properties.`$lib_version`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$initial_utm_campaign" {
      expr        = "person_properties.`$initial_utm_campaign`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$initial_utm_medium" {
      expr        = "person_properties.`$initial_utm_medium`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$initial_gclid" {
      expr        = "person_properties.`$initial_gclid`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$initial_gad_source" {
      expr        = "person_properties.`$initial_gad_source`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$initial_utm_source" {
      expr        = "person_properties.`$initial_utm_source`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$initial_referring_domain" {
      expr        = "person_properties.`$initial_referring_domain`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$initial_utm_term" {
      expr        = "person_properties.`$initial_utm_term`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$initial_utm_content" {
      expr        = "person_properties.`$initial_utm_content`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$initial_gbraid" {
      expr        = "person_properties.`$initial_gbraid`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$initial_wbraid" {
      expr        = "person_properties.`$initial_wbraid`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$initial_msclkid" {
      expr        = "person_properties.`$initial_msclkid`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$initial_fbclid" {
      expr        = "person_properties.`$initial_fbclid`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$geoip_subdivision_1_code" {
      expr        = "properties.`$geoip_subdivision_1_code`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$prev_pageview_max_scroll_percentage" {
      expr        = "properties.`$prev_pageview_max_scroll_percentage`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$prev_pageview_max_content_percentage" {
      expr        = "properties.`$prev_pageview_max_content_percentage`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$prev_pageview_pathname" {
      expr        = "properties.`$prev_pageview_pathname`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$initial_pathname" {
      expr        = "person_properties.`$initial_pathname`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$geoip_country_code" {
      expr        = "person_properties.`$geoip_country_code`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$browser_version" {
      expr        = "properties.`$browser_version`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$initial_current_url" {
      expr        = "person_properties.`$initial_current_url`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$current_url" {
      expr        = "person_properties.`$current_url`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$app_namespace" {
      expr        = "properties.`$app_namespace`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$os_name" {
      expr        = "properties.`$os_name`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$os_name" {
      expr        = "person_properties.`$os_name`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$app_version" {
      expr        = "person_properties.`$app_version`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$screen_height" {
      expr        = "properties.`$screen_height`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$screen_width" {
      expr        = "properties.`$screen_width`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$app_build" {
      expr        = "properties.`$app_build`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$geoip_country_code" {
      expr        = "properties.`$geoip_country_code`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$survey_id" {
      expr        = "properties.`$survey_id`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$survey_response_1" {
      expr        = "properties.`$survey_response_1`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$survey_response" {
      expr        = "properties.`$survey_response`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$el_text" {
      expr        = "properties.`$el_text`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$os_version" {
      expr        = "properties.`$os_version`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$feature_flag_payloads" {
      expr        = "properties.`$feature_flag_payloads`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$groups" {
      expr        = "properties.`$groups`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$feature_flag" {
      expr        = "properties.`$feature_flag`"
      type        = "minmax"
      granularity = 1
    }
    index "bf_active_feature_flags" {
      expr        = "properties.`$active_feature_flags`"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "minmax_mat_$device_id" {
      expr        = "properties.`$device_id`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$geoip_continent_name" {
      expr        = "person_properties.`$geoip_continent_name`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$feature_flag_response" {
      expr        = "properties.`$feature_flag_response`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$referring_domain" {
      expr        = "person_properties.`$referring_domain`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$lib_version__minor" {
      expr        = "properties.`$lib_version__minor`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_inserted_at" {
      expr        = "coalesce(inserted_at, _timestamp)"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$lib_custom_api_host" {
      expr        = "properties.`$lib_custom_api_host`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_pp_$geoip_country_name" {
      expr        = "person_properties.`$geoip_country_name`"
      type        = "minmax"
      granularity = 1
    }
    index "is_deleted_idx" {
      expr        = "is_deleted"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$device" {
      expr        = "properties.`$device`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$exception_issue_id" {
      expr        = "properties.`$exception_issue_id`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$exception_fingerprint" {
      expr        = "properties.`$exception_fingerprint`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$web_vitals_LCP_value" {
      expr        = "properties.`$web_vitals_LCP_value`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$web_vitals_FCP_value" {
      expr        = "properties.`$web_vitals_FCP_value`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$web_vitals_CLS_value" {
      expr        = "properties.`$web_vitals_CLS_value`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$web_vitals_INP_value" {
      expr        = "properties.`$web_vitals_INP_value`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$viewport_width" {
      expr        = "properties.`$viewport_width`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$viewport_height" {
      expr        = "properties.`$viewport_height`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$anon_distinct_id" {
      expr        = "properties.`$anon_distinct_id`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$ai_trace_id" {
      expr        = "properties.`$ai_trace_id`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$ai_model" {
      expr        = "properties.`$ai_model`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$ai_provider" {
      expr        = "properties.`$ai_provider`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$ai_parent_id" {
      expr        = "properties.`$ai_parent_id`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$ai_span_id" {
      expr        = "properties.`$ai_span_id`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$ai_http_status" {
      expr        = "properties.`$ai_http_status`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$process_person_profile" {
      expr        = "properties.`$process_person_profile`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$app_version" {
      expr        = "properties.`$app_version`"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_mat_$is_identified" {
      expr        = "properties.`$is_identified`"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_$session_id_uuid" {
      expr        = "toUInt128(toUUIDOrNull(properties.`$session_id`))"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_filter_$ai_trace_id" {
      expr        = "properties.`$ai_trace_id`"
      type        = "bloom_filter(0.001)"
      granularity = 2
    }
    index "bloom_filter_$ai_session_id" {
      expr        = "properties.`$ai_session_id`"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_$ai_session_id" {
      expr        = "properties.`$ai_session_id`"
      type        = "minmax"
      granularity = 1
    }
    index "set_$ai_is_error" {
      expr        = "properties.`$ai_is_error`"
      type        = "set(7)"
      granularity = 1
    }
    index "minmax_mat_$ai_total_cost_usd" {
      expr        = "properties.`$ai_total_cost_usd`"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_filter_distinct_id" {
      expr        = "distinct_id"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_sharded_events_timestamp" {
      expr        = "timestamp"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_historical_migration" {
      expr        = "historical_migration"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_mat_$feature_flag" {
      expr        = "properties.`$feature_flag`"
      type        = "bloom_filter"
      granularity = 1
    }
    index "bloom_filter_$ai_prompt_name" {
      expr        = "properties.`$ai_prompt_name`"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_$ai_prompt_name" {
      expr        = "properties.`$ai_prompt_name`"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_filter_$ai_experiment_id" {
      expr        = "properties.`$ai_experiment_id`"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_$ai_experiment_id" {
      expr        = "properties.`$ai_experiment_id`"
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
