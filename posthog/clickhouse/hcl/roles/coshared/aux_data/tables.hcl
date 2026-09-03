# Distributed proxies onto the aux cluster (and their column abstracts), co-hosted
# by the aux role (all envs) and the local data node. One declaration; both stacks
# compose this layer. The sharded_* storage tables stay in roles/auxiliary/shared.
database "posthog" {
  table "_conversion_goal_attributed_preaggregated_columns" {
    abstract = true
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "person_id" {
      type = "UUID"
    }
    column "conversion_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "conversion_value" {
      type = "Float64"
    }
    column "touchpoint_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "touchpoint_weight" {
      type = "Float64"
    }
    column "campaign_name" {
      type = "String"
    }
    column "source_name" {
      type = "String"
    }
    column "medium_name" {
      type = "String"
    }
    column "content_name" {
      type = "String"
    }
    column "term_name" {
      type = "String"
    }
    column "referring_domain_name" {
      type = "String"
    }
    column "gclid_name" {
      type = "String"
    }
    column "fbclid_name" {
      type = "String"
    }
    column "gad_source_name" {
      type = "String"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "Date"
      default = "today() + toIntervalDay(7)"
    }
  }
  table "_experiment_metric_events_preaggregated_columns" {
    abstract = true
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "entity_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "event_uuid" {
      type = "UUID"
    }
    column "session_id" {
      type = "String"
    }
    column "numeric_value" {
      type    = "Float64"
      default = "0"
    }
    column "steps" {
      type    = "Array(UInt8)"
      default = "[]"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "Date"
      default = "today() + toIntervalDay(7)"
    }
  }
  table "_ingestion_warnings_v2_columns" {
    abstract = true
    column "team_id" {
      type = "Int64"
    }
    column "source" {
      type = "LowCardinality(String)"
    }
    column "type" {
      type = "LowCardinality(String)"
    }
    column "details" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "category" {
      type         = "LowCardinality(String)"
      default      = "coalesce(nullIf(JSONExtractString(details, 'category'), ''), 'unknown')"
    }
    column "severity" {
      type         = "LowCardinality(String)"
      default      = "coalesce(nullIf(JSONExtractString(details, 'severity'), ''), 'warning')"
    }
    column "pipeline_step" {
      type         = "LowCardinality(String)"
      default      = "coalesce(nullIf(JSONExtractString(details, 'pipelineStep'), ''), 'unknown')"
    }
    column "event_uuid" {
      type         = "Nullable(UUID)"
      default      = "toUUIDOrNull(JSONExtractString(details, 'eventUuid'))"
    }
    column "distinct_id" {
      type         = "Nullable(String)"
      default      = "nullIf(JSONExtractString(details, 'distinctId'), '')"
    }
    column "group_key" {
      type         = "Nullable(String)"
      default      = "nullIf(JSONExtractString(details, 'groupKey'), '')"
    }
    column "person_id" {
      type         = "Nullable(UUID)"
      default      = "toUUIDOrNull(JSONExtractString(details, 'personId'))"
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
  }
  table "_marketing_conversions_preaggregated_columns" {
    abstract = true
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "person_id" {
      type = "UUID"
    }
    column "conversion_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "conversion_math_value" {
      type = "Float64"
    }
    column "session_id" {
      type = "String"
    }
    column "campaign_name" {
      type = "String"
    }
    column "source_name" {
      type = "String"
    }
    column "medium_name" {
      type = "String"
    }
    column "content_name" {
      type = "String"
    }
    column "term_name" {
      type = "String"
    }
    column "referring_domain_name" {
      type = "String"
    }
    column "gclid_name" {
      type = "String"
    }
    column "fbclid_name" {
      type = "String"
    }
    column "gad_source_name" {
      type = "String"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "Date"
      default = "today() + toIntervalDay(7)"
    }
  }
  table "_marketing_costs_preaggregated_columns" {
    abstract = true
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "source_id" {
      type = "String"
    }
    column "source_name" {
      type = "String"
    }
    column "grain" {
      type = "LowCardinality(String)"
    }
    column "match_key" {
      type = "String"
    }
    column "campaign_id" {
      type = "String"
    }
    column "campaign_name" {
      type = "String"
    }
    column "ad_group_id" {
      type = "String"
    }
    column "ad_group_name" {
      type = "String"
    }
    column "ad_id" {
      type = "String"
    }
    column "ad_name" {
      type = "String"
    }
    column "cost_date" {
      type = "Date"
    }
    column "cost" {
      type = "Float64"
    }
    column "clicks" {
      type = "Float64"
    }
    column "impressions" {
      type = "Float64"
    }
    column "reported_conversions" {
      type = "Float64"
    }
    column "reported_conversion_value" {
      type = "Float64"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "Date"
      default = "today() + toIntervalDay(7)"
    }
  }
  table "_marketing_touchpoints_preaggregated_columns" {
    abstract = true
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "person_id" {
      type = "UUID"
    }
    column "touchpoint_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "campaign_name" {
      type = "String"
    }
    column "source_name" {
      type = "String"
    }
    column "medium_name" {
      type = "String"
    }
    column "content_name" {
      type = "String"
    }
    column "term_name" {
      type = "String"
    }
    column "referring_domain_name" {
      type = "String"
    }
    column "gclid_name" {
      type = "String"
    }
    column "fbclid_name" {
      type = "String"
    }
    column "gad_source_name" {
      type = "String"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "Date"
      default = "today() + toIntervalDay(7)"
    }
  }
  table "_session_replay_features_columns" {
    abstract = true
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "min_first_timestamp" {
      type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))"
    }
    column "max_last_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "event_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "mouse_position_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "mouse_sum_x" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "mouse_sum_x_squared" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "mouse_sum_y" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "mouse_sum_y_squared" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "mouse_distance_traveled" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "mouse_direction_change_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "mouse_velocity_sum" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "mouse_velocity_sum_of_squares" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "mouse_velocity_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "scroll_event_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "total_scroll_magnitude" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "scroll_direction_reversal_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "rapid_scroll_reversal_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "scroll_to_top_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "click_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "keypress_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "mouse_activity_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "rage_click_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "dead_click_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "backspace_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "inter_action_gap_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "inter_action_gap_sum_ms" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "inter_action_gap_sum_of_squares_ms" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "max_idle_gap_ms" {
      type = "SimpleAggregateFunction(max, Float64)"
    }
    column "long_idle_gap_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "quick_back_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "page_visit_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "unique_url_count" {
      type = "AggregateFunction(uniqCombined(12), String)"
    }
    column "login_path_visit_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "signup_path_visit_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "checkout_path_visit_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "cart_path_visit_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "billing_path_visit_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "settings_path_visit_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "account_path_visit_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "error_path_visit_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "not_found_path_visit_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "admin_path_visit_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "dashboard_path_visit_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "onboarding_path_visit_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "cancel_path_visit_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "refund_path_visit_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "console_error_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "console_error_after_click_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "console_warn_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "network_request_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "network_failed_request_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "network_4xx_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "network_5xx_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "network_request_duration_sum" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "network_request_duration_sum_of_squares" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "network_request_duration_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "mutation_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "viewport_resize_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "touch_event_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "max_scroll_y" {
      type = "SimpleAggregateFunction(max, Float64)"
    }
    column "unique_click_target_count" {
      type = "AggregateFunction(uniqCombined(12), Int64)"
    }
    column "unique_form_field_count" {
      type = "AggregateFunction(uniqCombined(12), Int64)"
    }
    column "text_selection_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "selection_copy_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "is_deleted" {
      type    = "SimpleAggregateFunction(max, UInt8)"
      default = "0"
    }
  }
  table "_web_bot_definition_columns" {
    abstract = true
    column "id" {
      type = "UInt64"
    }
    column "parent_id" {
      type = "UInt64"
    }
    column "regexp" {
      type = "String"
    }
    column "keys" {
      type = "Array(String)"
    }
    column "values" {
      type = "Array(String)"
    }
  }
  table "_web_bounces_dimensional_preaggregated_columns" {
    abstract = true
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "period_bucket" {
      type = "DateTime"
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
    column "mat_metadata_backend" {
      type = "Nullable(String)"
    }
    column "mat_metadata_loggedIn" {
      type = "Nullable(Bool)"
    }
    column "persons_uniq_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sessions_uniq_state" {
      type = "AggregateFunction(uniq, String)"
    }
    column "pageviews_count_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "bounces_count_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "total_session_duration_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "total_session_count_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
  }
  table "_web_goals_preaggregated_columns" {
    abstract = true
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "time_window_start" {
      type = "DateTime64(6, 'UTC')"
    }
    column "action_id" {
      type = "Int64"
    }
    column "count_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "unique_persons_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
  }
  table "_web_stats_dimensional_preaggregated_columns" {
    abstract = true
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "period_bucket" {
      type = "DateTime"
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
    column "mat_metadata_backend" {
      type = "Nullable(String)"
    }
    column "mat_metadata_loggedIn" {
      type = "Nullable(Bool)"
    }
    column "persons_uniq_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sessions_uniq_state" {
      type = "AggregateFunction(uniq, String)"
    }
    column "pageviews_count_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
  }
  table "_web_stats_frustration_preaggregated_columns" {
    abstract = true
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "time_window_start" {
      type = "DateTime64(6, 'UTC')"
    }
    column "breakdown_value" {
      type = "String"
    }
    column "sum_rage_clicks_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "sum_dead_clicks_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "sum_errors_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
  }
  table "_web_stats_preaggregated_columns" {
    abstract = true
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "time_window_start" {
      type = "DateTime64(6, 'UTC')"
    }
    column "breakdown_by" {
      type = "String"
    }
    column "breakdown_value" {
      type = "String"
    }
    column "uniq_users_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sum_pageviews_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
  }
  table "_web_vitals_paths_preaggregated_columns" {
    abstract = true
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "time_window_start" {
      type = "DateTime64(6, 'UTC')"
    }
    column "path" {
      type = "String"
    }
    column "inp_quantiles_state" {
      type = "AggregateFunction(quantiles(0.75, 0.9, 0.99), Float64)"
    }
    column "lcp_quantiles_state" {
      type = "AggregateFunction(quantiles(0.75, 0.9, 0.99), Float64)"
    }
    column "cls_quantiles_state" {
      type = "AggregateFunction(quantiles(0.75, 0.9, 0.99), Float64)"
    }
    column "fcp_quantiles_state" {
      type = "AggregateFunction(quantiles(0.75, 0.9, 0.99), Float64)"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
  }
  table "conversion_goal_attributed_preaggregated" {
    extend = "_conversion_goal_attributed_preaggregated_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_conversion_goal_attributed_preaggregated"
      sharding_key    = "cityHash64(person_id)"
    }
  }
  table "error_tracking_fingerprint_issue_state" {
    column "team_id" {
      type = "Int64"
    }
    column "fingerprint" {
      type = "String"
    }
    column "issue_id" {
      type = "UUID"
    }
    column "issue_name" {
      type = "Nullable(String)"
    }
    column "issue_description" {
      type = "Nullable(String)"
    }
    column "issue_status" {
      type = "String"
    }
    column "issue_severity" {
      type = "Nullable(String)"
    }
    column "assigned_user_id" {
      type = "Nullable(Int64)"
    }
    column "assigned_role_id" {
      type = "Nullable(UUID)"
    }
    column "first_seen" {
      type = "DateTime64(3, 'UTC')"
    }
    column "is_deleted" {
      type = "Int8"
    }
    column "version" {
      type = "Int64"
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
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "raw_error_tracking_fingerprint_issue_state"
    }
  }
  table "experiment_metric_events_preaggregated" {
    extend = "_experiment_metric_events_preaggregated_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_experiment_metric_events_preaggregated"
      sharding_key    = "cityHash64(entity_id)"
    }
  }
  table "hog_invocation_results" {
    column "team_id" {
      type = "Int64"
    }
    column "function_kind" {
      type = "LowCardinality(String)"
    }
    column "function_id" {
      type = "String"
    }
    column "invocation_id" {
      type = "String"
    }
    column "parent_run_id" {
      type = "String"
    }
    column "status" {
      type = "LowCardinality(String)"
    }
    column "attempts" {
      type = "UInt8"
    }
    column "is_retry" {
      type = "UInt8"
    }
    column "scheduled_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "first_scheduled_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "started_at" {
      type = "Nullable(DateTime64(6, 'UTC'))"
    }
    column "finished_at" {
      type = "Nullable(DateTime64(6, 'UTC'))"
    }
    column "duration_ms" {
      type = "Nullable(UInt32)"
    }
    column "error_kind" {
      type = "LowCardinality(String)"
    }
    column "error_message" {
      type = "String"
    }
    column "event_uuid" {
      type = "String"
    }
    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "String"
    }
    column "invocation_globals" {
      type = "String"
    }
    column "version" {
      type = "UInt64"
    }
    column "is_deleted" {
      type = "UInt8"
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
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "hog_invocation_results_data"
    }
  }
  table "ingestion_warnings_v2_distributed" {
    extend = "_ingestion_warnings_v2_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "ingestion_warnings_v2"
    }
  }
  table "marketing_conversions_preaggregated" {
    extend = "_marketing_conversions_preaggregated_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_marketing_conversions_preaggregated"
      sharding_key    = "cityHash64(person_id)"
    }
  }
  table "marketing_costs_preaggregated" {
    extend = "_marketing_costs_preaggregated_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_marketing_costs_preaggregated"
      sharding_key    = "cityHash64(source_name, campaign_id)"
    }
  }
  table "marketing_touchpoints_preaggregated" {
    extend = "_marketing_touchpoints_preaggregated_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_marketing_touchpoints_preaggregated"
      sharding_key    = "cityHash64(person_id)"
    }
  }
  table "message_assets" {
    column "team_id" {
      type = "Int64"
    }
    column "function_kind" {
      type = "LowCardinality(String)"
    }
    column "function_id" {
      type = "String"
    }
    column "parent_run_id" {
      type = "String"
    }
    column "invocation_id" {
      type = "String"
    }
    column "action_id" {
      type = "String"
    }
    column "kind" {
      type = "LowCardinality(String)"
    }
    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "String"
    }
    column "recipient" {
      type = "String"
    }
    column "subject" {
      type = "String"
    }
    column "status" {
      type = "LowCardinality(String)"
    }
    column "sent_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "version" {
      type = "UInt64"
    }
    column "is_deleted" {
      type = "UInt8"
    }
    column "html" {
      type = "String"
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
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "message_assets_data"
    }
  }
  table "property_values_distributed" {
    column "team_id" {
      type  = "Int64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "property_type" {
      type = "LowCardinality(String)"
    }
    column "property_key" {
      type = "LowCardinality(String)"
    }
    column "property_value" {
      type = "String"
    }
    column "property_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "last_seen" {
      type    = "SimpleAggregateFunction(max, DateTime)"
      default = "now()"
    }
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "property_values"
    }
  }
  table "session_replay_features" {
    extend = "_session_replay_features_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_session_replay_features"
      sharding_key    = "sipHash64(session_id)"
    }
  }
  table "web_bot_definition" {
    extend = "_web_bot_definition_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_bot_definition"
      sharding_key    = "sipHash64(id)"
    }
  }
  table "web_bounces_dimensional_preaggregated" {
    extend = "_web_bounces_dimensional_preaggregated_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_bounces_dimensional_preaggregated"
      sharding_key    = "sipHash64(job_id)"
    }
  }
  table "web_goals_preaggregated" {
    extend = "_web_goals_preaggregated_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_goals_preaggregated"
      sharding_key    = "sipHash64(job_id)"
    }
  }
  table "web_stats_dimensional_preaggregated" {
    extend = "_web_stats_dimensional_preaggregated_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_stats_dimensional_preaggregated"
      sharding_key    = "sipHash64(job_id)"
    }
  }
  table "web_stats_frustration_preaggregated" {
    extend = "_web_stats_frustration_preaggregated_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_stats_frustration_preaggregated"
      sharding_key    = "sipHash64(job_id)"
    }
  }
  table "web_stats_preaggregated" {
    extend = "_web_stats_preaggregated_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_stats_preaggregated"
      sharding_key    = "sipHash64(job_id)"
    }
  }
  table "web_vitals_paths_preaggregated" {
    extend = "_web_vitals_paths_preaggregated_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_vitals_paths_preaggregated"
      sharding_key    = "sipHash64(job_id)"
    }
  }
  dictionary "web_bot_definition_dict" {
    primary_key = ["regexp"]
    lifetime {
      min = 3000
      max = 3600
    }
    attribute "regexp" {
      type = "String"
    }
    attribute "name" {
      type = "String"
    }
    attribute "category" {
      type = "String"
    }
    attribute "traffic_type" {
      type = "String"
    }
    attribute "operator" {
      type = "String"
    }
    source "clickhouse" {
      user  = "default"
      db    = "posthog"
      table = "web_bot_definition"
    }
    layout "regexp_tree" {
    }
  }
}
