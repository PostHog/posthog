database "posthog" {
  table "writable_events_json" {
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
      type    = "String"
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
      type    = "Nullable(DateTime64(6, 'UTC'))"
      default = "now64()"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "is_deleted" {
      type    = "Bool"
      default = "false"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
    column "historical_migration" {
      type    = "Bool"
      default = "false"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_events_json"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }
}
