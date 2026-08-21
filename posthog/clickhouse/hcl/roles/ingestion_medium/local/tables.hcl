node "medium" {
  macros = {
    hostClusterRole = "medium"
    hostClusterType = "online"
    replica         = "medium"
    shard           = "01"
  }
}

database "posthog" {
  table "kafka_app_metrics2" {
    column "team_id" {
      type = "Int64"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "app_source" {
      type = "LowCardinality(String)"
    }
    column "app_source_id" {
      type = "String"
    }
    column "instance_id" {
      type = "String"
    }
    column "metric_kind" {
      type = "String"
    }
    column "metric_name" {
      type = "String"
    }
    column "count" {
      type = "Int64"
    }
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_app_metrics2'"
      group_name  = "kafka_group_name = 'group1'"
      format      = "kafka_format = 'JSONEachRow'"
    }
  }

  table "kafka_app_metrics2_ws" {
    column "team_id" {
      type = "Int64"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "app_source" {
      type = "LowCardinality(String)"
    }
    column "app_source_id" {
      type = "String"
    }
    column "instance_id" {
      type = "String"
    }
    column "metric_kind" {
      type = "String"
    }
    column "metric_name" {
      type = "String"
    }
    column "count" {
      type = "Int64"
    }
    engine "kafka" {
      broker_list = "warpstream_ingestion"
      topic_list  = "kafka_topic_list = 'clickhouse_app_metrics2'"
      group_name  = "kafka_group_name = 'clickhouse_app_metrics2_ws'"
      format      = "kafka_format = 'JSONEachRow'"
    }
  }

  table "kafka_cohort_membership" {
    column "team_id" {
      type = "Int64"
    }
    column "cohort_id" {
      type = "Int64"
    }
    column "person_id" {
      type = "UUID"
    }
    column "status" {
      type = "Enum8('entered'=1, 'left'=2, 'member'=3, 'not_member'=4)"
    }
    column "last_updated" {
      type = "DateTime64(6)"
    }
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'cohort_membership_changed'"
      group_name  = "kafka_group_name = 'clickhouse_cohort_membership_changed'"
      format      = "kafka_format = 'JSONEachRow'"
    }
  }

  table "kafka_distinct_id_usage" {
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    engine "kafka" {
      broker_list          = "warpstream_ingestion"
      topic_list           = "kafka_topic_list = 'distinct_id_usage_events_json'"
      group_name           = "kafka_group_name = 'clickhouse_distinct_id_usage'"
      format               = "kafka_format = 'JSONEachRow'"
      skip_broken_messages = 100
    }
  }

  table "kafka_flag_evaluations" {
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "LowCardinality(String)"
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
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "person_id" {
      type = "UUID"
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
    column "inserted_at" {
      type = "DateTime64(6, 'UTC')"
    }
    engine "kafka" {
      broker_list          = "warpstream_ingestion"
      topic_list           = "kafka_topic_list = 'clickhouse_flag_evaluations'"
      group_name           = "kafka_group_name = 'clickhouse_flag_evaluations'"
      format               = "kafka_format = 'JSONEachRow'"
      skip_broken_messages = 100
    }
  }

  table "kafka_heatmaps" {
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "x" {
      type = "Int16"
    }
    column "y" {
      type = "Int16"
    }
    column "scale_factor" {
      type = "Int16"
    }
    column "viewport_width" {
      type = "Int16"
    }
    column "viewport_height" {
      type = "Int16"
    }
    column "pointer_target_fixed" {
      type = "Bool"
    }
    column "current_url" {
      type = "String"
    }
    column "type" {
      type = "LowCardinality(String)"
    }
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_heatmap_events'"
      group_name  = "kafka_group_name = 'group1'"
      format      = "kafka_format = 'JSONEachRow'"
    }
  }

  table "kafka_precalculated_events" {
    column "team_id" {
      type = "Int64"
    }
    column "date" {
      type = "Nullable(Date)"
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
    engine "kafka" {
      broker_list          = "msk_cluster"
      topic_list           = "kafka_topic_list = 'clickhouse_prefiltered_events'"
      group_name           = "kafka_group_name = 'clickhouse_prefiltered_events'"
      format               = "kafka_format = 'JSONEachRow'"
      num_consumers        = 1
      max_block_size       = 1000000
      skip_broken_messages = 100
      poll_timeout_ms      = 1000
      poll_max_batch_size  = 100000
      flush_interval_ms    = 7500
    }
  }

  table "kafka_precalculated_person_properties" {
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
    engine "kafka" {
      broker_list          = "msk_cluster"
      topic_list           = "kafka_topic_list = 'clickhouse_precalculated_person_properties'"
      group_name           = "kafka_group_name = 'clickhouse_precalculated_person_properties'"
      format               = "kafka_format = 'JSONEachRow'"
      num_consumers        = 1
      max_block_size       = 1000000
      skip_broken_messages = 100
      poll_timeout_ms      = 1000
      poll_max_batch_size  = 100000
      flush_interval_ms    = 7500
    }
  }

  table "kafka_precalculated_person_properties_ws" {
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
    engine "kafka" {
      broker_list          = "warpstream_calculated_events"
      topic_list           = "kafka_topic_list = 'clickhouse_precalculated_person_properties'"
      group_name           = "kafka_group_name = 'clickhouse_precalculated_person_properties_ws'"
      format               = "kafka_format = 'JSONEachRow'"
      num_consumers        = 1
      max_block_size       = 1000000
      skip_broken_messages = 100
      poll_timeout_ms      = 1000
      poll_max_batch_size  = 100000
      flush_interval_ms    = 7500
    }
  }

  table "kafka_session_replay_features" {
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "batch_id" {
      type = "String"
    }
    column "first_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "last_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "event_count" {
      type = "Int64"
    }
    column "mouse_position_count" {
      type = "Int64"
    }
    column "mouse_sum_x" {
      type = "Float64"
    }
    column "mouse_sum_x_squared" {
      type = "Float64"
    }
    column "mouse_sum_y" {
      type = "Float64"
    }
    column "mouse_sum_y_squared" {
      type = "Float64"
    }
    column "mouse_distance_traveled" {
      type = "Float64"
    }
    column "mouse_direction_change_count" {
      type = "Int64"
    }
    column "mouse_velocity_sum" {
      type = "Float64"
    }
    column "mouse_velocity_sum_of_squares" {
      type = "Float64"
    }
    column "mouse_velocity_count" {
      type = "Int64"
    }
    column "scroll_event_count" {
      type = "Int64"
    }
    column "total_scroll_magnitude" {
      type = "Float64"
    }
    column "scroll_direction_reversal_count" {
      type = "Int64"
    }
    column "rapid_scroll_reversal_count" {
      type = "Int64"
    }
    column "scroll_to_top_count" {
      type = "Int64"
    }
    column "click_count" {
      type = "Int64"
    }
    column "keypress_count" {
      type = "Int64"
    }
    column "mouse_activity_count" {
      type = "Int64"
    }
    column "rage_click_count" {
      type = "Int64"
    }
    column "dead_click_count" {
      type = "Int64"
    }
    column "backspace_count" {
      type = "Int64"
    }
    column "inter_action_gap_count" {
      type = "Int64"
    }
    column "inter_action_gap_sum_ms" {
      type = "Float64"
    }
    column "inter_action_gap_sum_of_squares_ms" {
      type = "Float64"
    }
    column "max_idle_gap_ms" {
      type = "Float64"
    }
    column "long_idle_gap_count" {
      type = "Int64"
    }
    column "quick_back_count" {
      type = "Int64"
    }
    column "page_visit_count" {
      type = "Int64"
    }
    column "visited_urls" {
      type = "Array(String)"
    }
    column "login_path_visit_count" {
      type = "Int64"
    }
    column "signup_path_visit_count" {
      type = "Int64"
    }
    column "checkout_path_visit_count" {
      type = "Int64"
    }
    column "cart_path_visit_count" {
      type = "Int64"
    }
    column "billing_path_visit_count" {
      type = "Int64"
    }
    column "settings_path_visit_count" {
      type = "Int64"
    }
    column "account_path_visit_count" {
      type = "Int64"
    }
    column "error_path_visit_count" {
      type = "Int64"
    }
    column "not_found_path_visit_count" {
      type = "Int64"
    }
    column "admin_path_visit_count" {
      type = "Int64"
    }
    column "dashboard_path_visit_count" {
      type = "Int64"
    }
    column "onboarding_path_visit_count" {
      type = "Int64"
    }
    column "cancel_path_visit_count" {
      type = "Int64"
    }
    column "refund_path_visit_count" {
      type = "Int64"
    }
    column "console_error_count" {
      type = "Int64"
    }
    column "console_error_after_click_count" {
      type = "Int64"
    }
    column "console_warn_count" {
      type = "Int64"
    }
    column "network_request_count" {
      type = "Int64"
    }
    column "network_failed_request_count" {
      type = "Int64"
    }
    column "network_4xx_count" {
      type = "Int64"
    }
    column "network_5xx_count" {
      type = "Int64"
    }
    column "network_request_duration_sum" {
      type = "Float64"
    }
    column "network_request_duration_sum_of_squares" {
      type = "Float64"
    }
    column "network_request_duration_count" {
      type = "Int64"
    }
    column "mutation_count" {
      type = "Int64"
    }
    column "viewport_resize_count" {
      type = "Int64"
    }
    column "touch_event_count" {
      type = "Int64"
    }
    column "max_scroll_y" {
      type = "Float64"
    }
    column "click_target_ids" {
      type = "Array(Int64)"
    }
    column "form_field_ids" {
      type = "Array(Int64)"
    }
    column "text_selection_count" {
      type = "Int64"
    }
    column "selection_copy_count" {
      type = "Int64"
    }
    column "is_deleted" {
      type = "UInt8"
    }
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_session_replay_features'"
      group_name  = "kafka_group_name = 'group1'"
      format      = "kafka_format = 'JSONEachRow'"
    }
  }

  table "kafka_tophog" {
    settings = {
      date_time_input_format = "best_effort"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "metric" {
      type = "LowCardinality(String)"
    }
    column "type" {
      type = "LowCardinality(String)"
    }
    column "key" {
      type = "Map(LowCardinality(String), String)"
    }
    column "value" {
      type = "Float64"
    }
    column "count" {
      type = "UInt64"
    }
    column "pipeline" {
      type = "LowCardinality(String)"
    }
    column "lane" {
      type = "LowCardinality(String)"
    }
    column "labels" {
      type = "Map(LowCardinality(String), String)"
    }
    engine "kafka" {
      broker_list          = "msk_cluster"
      topic_list           = "kafka_topic_list = 'clickhouse_tophog'"
      group_name           = "kafka_group_name = 'clickhouse_tophog'"
      format               = "kafka_format = 'JSONEachRow'"
      skip_broken_messages = 100
    }
  }

  table "kafka_tophog_ws" {
    settings = {
      date_time_input_format = "best_effort"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "metric" {
      type = "LowCardinality(String)"
    }
    column "type" {
      type = "LowCardinality(String)"
    }
    column "key" {
      type = "Map(LowCardinality(String), String)"
    }
    column "value" {
      type = "Float64"
    }
    column "count" {
      type = "UInt64"
    }
    column "pipeline" {
      type = "LowCardinality(String)"
    }
    column "lane" {
      type = "LowCardinality(String)"
    }
    column "labels" {
      type = "Map(LowCardinality(String), String)"
    }
    engine "kafka" {
      broker_list          = "warpstream_ingestion"
      topic_list           = "kafka_topic_list = 'clickhouse_tophog'"
      group_name           = "kafka_group_name = 'clickhouse_tophog_ws'"
      format               = "kafka_format = 'JSONEachRow'"
      skip_broken_messages = 100
    }
  }

  table "writable_app_metrics2" {
    column "team_id" {
      type = "Int64"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "app_source" {
      type = "LowCardinality(String)"
    }
    column "app_source_id" {
      type = "String"
    }
    column "instance_id" {
      type = "String"
    }
    column "metric_kind" {
      type = "LowCardinality(String)"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "count" {
      type = "SimpleAggregateFunction(sum, Int64)"
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
      remote_table    = "sharded_app_metrics2"
      sharding_key    = "rand()"
    }
  }

  table "writable_cohort_membership" {
    column "team_id" {
      type = "Int64"
    }
    column "cohort_id" {
      type = "Int64"
    }
    column "person_id" {
      type = "UUID"
    }
    column "status" {
      type = "Enum8('entered'=1, 'left'=2)"
    }
    column "last_updated" {
      type    = "DateTime64(6)"
      default = "now64()"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "cohort_membership"
    }
  }

  table "writable_distinct_id_usage" {
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "minute" {
      type = "DateTime"
    }
    column "event_count" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_distinct_id_usage"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }

  table "writable_flag_evaluations" {
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "LowCardinality(String)"
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
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "person_id" {
      type = "UUID"
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
    column "inserted_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "timestamp"
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
      remote_table    = "sharded_flag_evaluations"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }

  table "writable_heatmaps" {
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "x" {
      type = "Int16"
    }
    column "y" {
      type = "Int16"
    }
    column "scale_factor" {
      type = "Int16"
    }
    column "viewport_width" {
      type = "Int16"
    }
    column "viewport_height" {
      type = "Int16"
    }
    column "pointer_target_fixed" {
      type = "Bool"
    }
    column "current_url" {
      type = "String"
    }
    column "type" {
      type = "LowCardinality(String)"
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
      remote_table    = "sharded_heatmaps"
      sharding_key    = "cityHash64(concat(toString(team_id), '-', session_id, '-', toString(toDate(timestamp))))"
    }
  }

  table "writable_precalculated_events" {
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

  table "writable_precalculated_person_properties" {
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

  table "writable_session_replay_features" {
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
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_session_replay_features"
      sharding_key    = "sipHash64(session_id)"
    }
  }

  table "writable_tophog" {
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "metric" {
      type = "LowCardinality(String)"
    }
    column "type" {
      type    = "LowCardinality(String)"
      default = "'sum'"
    }
    column "key" {
      type = "Map(LowCardinality(String), String)"
    }
    column "value" {
      type = "Float64"
    }
    column "count" {
      type    = "UInt64"
      default = "0"
    }
    column "pipeline" {
      type = "LowCardinality(String)"
    }
    column "lane" {
      type = "LowCardinality(String)"
    }
    column "labels" {
      type = "Map(LowCardinality(String), String)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_tophog"
      sharding_key    = "cityHash64(toString(key))"
    }
  }

  materialized_view "app_metrics2_mv" {
    to_table = "posthog.writable_app_metrics2"
    query    = <<SQL
SELECT
  team_id,
  timestamp,
  app_source,
  app_source_id,
  instance_id,
  metric_kind,
  metric_name,
  count,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_app_metrics2
SQL

    column "team_id" {
      type = "Int64"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "app_source" {
      type = "LowCardinality(String)"
    }
    column "app_source_id" {
      type = "String"
    }
    column "instance_id" {
      type = "String"
    }
    column "metric_kind" {
      type = "String"
    }
    column "metric_name" {
      type = "String"
    }
    column "count" {
      type = "Int64"
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

  materialized_view "app_metrics2_ws_mv" {
    to_table = "posthog.writable_app_metrics2"
    query    = <<SQL
SELECT
  team_id,
  timestamp,
  app_source,
  app_source_id,
  instance_id,
  metric_kind,
  metric_name,
  count,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_app_metrics2_ws
SQL

    column "team_id" {
      type = "Int64"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "app_source" {
      type = "LowCardinality(String)"
    }
    column "app_source_id" {
      type = "String"
    }
    column "instance_id" {
      type = "String"
    }
    column "metric_kind" {
      type = "String"
    }
    column "metric_name" {
      type = "String"
    }
    column "count" {
      type = "Int64"
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

  materialized_view "cohort_membership_mv" {
    to_table = "posthog.writable_cohort_membership"
    query    = <<SQL
SELECT
  team_id,
  cohort_id,
  person_id,
  multiIf(status = 'member', 'entered', status = 'not_member', 'left', status) AS status,
  last_updated
FROM posthog.kafka_cohort_membership
SQL

    column "team_id" {
      type = "Int64"
    }
    column "cohort_id" {
      type = "Int64"
    }
    column "person_id" {
      type = "UUID"
    }
    column "status" {
      type = "String"
    }
    column "last_updated" {
      type = "DateTime64(6)"
    }
  }

  materialized_view "distinct_id_usage_mv" {
    to_table = "posthog.writable_distinct_id_usage"
    query    = <<SQL
SELECT team_id, distinct_id, toStartOfMinute(timestamp) AS minute, 1 AS event_count
FROM posthog.kafka_distinct_id_usage
SQL

    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "minute" {
      type = "DateTime('UTC')"
    }
    column "event_count" {
      type = "UInt8"
    }
  }

  materialized_view "flag_evaluations_mv" {
    to_table = "posthog.writable_flag_evaluations"
    query    = <<SQL
SELECT
  uuid,
  event,
  properties,
  timestamp,
  team_id,
  distinct_id,
  created_at,
  person_id,
  person_properties,
  group0_properties,
  group1_properties,
  group2_properties,
  group3_properties,
  group4_properties,
  if(inserted_at = toDateTime64('1970-01-01 00:00:00', 6, 'UTC'), _timestamp, inserted_at) AS inserted_at,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_flag_evaluations
SQL

    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "LowCardinality(String)"
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
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "person_id" {
      type = "UUID"
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
    column "inserted_at" {
      type = "Nullable(DateTime64(6, 'UTC'))"
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

  materialized_view "heatmaps_mv" {
    to_table = "posthog.writable_heatmaps"
    query    = <<SQL
SELECT
  session_id,
  team_id,
  distinct_id,
  timestamp,
  x,
  y,
  scale_factor,
  viewport_width,
  viewport_height,
  pointer_target_fixed,
  current_url,
  type,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_heatmaps
SQL

    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "x" {
      type = "Int16"
    }
    column "y" {
      type = "Int16"
    }
    column "scale_factor" {
      type = "Int16"
    }
    column "viewport_width" {
      type = "Int16"
    }
    column "viewport_height" {
      type = "Int16"
    }
    column "pointer_target_fixed" {
      type = "Bool"
    }
    column "current_url" {
      type = "String"
    }
    column "type" {
      type = "LowCardinality(String)"
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

  materialized_view "precalculated_events_mv" {
    to_table = "posthog.writable_precalculated_events"
    query    = <<SQL
SELECT
  team_id,
  ifNull(date, toDate(_timestamp)) AS date,
  distinct_id,
  person_id,
  condition,
  uuid,
  source,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_precalculated_events
SQL

    column "team_id" {
      type = "Int64"
    }
    column "date" {
      type = "Nullable(Date)"
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
      type = "Nullable(DateTime)"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_partition" {
      type = "UInt64"
    }
  }

  materialized_view "precalculated_person_properties_mv" {
    to_table = "posthog.writable_precalculated_person_properties"
    query    = <<SQL
SELECT
  team_id,
  distinct_id,
  person_id,
  condition,
  matches,
  source,
  _timestamp,
  _offset
FROM posthog.kafka_precalculated_person_properties
SQL

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
      type = "Nullable(DateTime)"
    }
    column "_offset" {
      type = "UInt64"
    }
  }

  materialized_view "precalculated_person_properties_ws_mv" {
    to_table = "posthog.writable_precalculated_person_properties"
    query    = <<SQL
SELECT
  team_id,
  distinct_id,
  person_id,
  condition,
  matches,
  source,
  _timestamp,
  _offset
FROM posthog.kafka_precalculated_person_properties_ws
SQL

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
      type = "Nullable(DateTime)"
    }
    column "_offset" {
      type = "UInt64"
    }
  }

  materialized_view "session_replay_features_mv" {
    to_table = "posthog.writable_session_replay_features"
    query    = <<SQL
SELECT
  session_id,
  team_id,
  any(distinct_id) AS distinct_id,
  min(first_timestamp) AS min_first_timestamp,
  max(last_timestamp) AS max_last_timestamp,
  sum(event_count) AS event_count,
  sum(mouse_position_count) AS mouse_position_count,
  sum(mouse_sum_x) AS mouse_sum_x,
  sum(mouse_sum_x_squared) AS mouse_sum_x_squared,
  sum(mouse_sum_y) AS mouse_sum_y,
  sum(mouse_sum_y_squared) AS mouse_sum_y_squared,
  sum(mouse_distance_traveled) AS mouse_distance_traveled,
  sum(mouse_direction_change_count) AS mouse_direction_change_count,
  sum(mouse_velocity_sum) AS mouse_velocity_sum,
  sum(mouse_velocity_sum_of_squares) AS mouse_velocity_sum_of_squares,
  sum(mouse_velocity_count) AS mouse_velocity_count,
  sum(scroll_event_count) AS scroll_event_count,
  sum(total_scroll_magnitude) AS total_scroll_magnitude,
  sum(scroll_direction_reversal_count) AS scroll_direction_reversal_count,
  sum(rapid_scroll_reversal_count) AS rapid_scroll_reversal_count,
  sum(scroll_to_top_count) AS scroll_to_top_count,
  sum(click_count) AS click_count,
  sum(keypress_count) AS keypress_count,
  sum(mouse_activity_count) AS mouse_activity_count,
  sum(rage_click_count) AS rage_click_count,
  sum(dead_click_count) AS dead_click_count,
  sum(backspace_count) AS backspace_count,
  sum(inter_action_gap_count) AS inter_action_gap_count,
  sum(inter_action_gap_sum_ms) AS inter_action_gap_sum_ms,
  sum(inter_action_gap_sum_of_squares_ms) AS inter_action_gap_sum_of_squares_ms,
  max(max_idle_gap_ms) AS max_idle_gap_ms,
  sum(long_idle_gap_count) AS long_idle_gap_count,
  sum(quick_back_count) AS quick_back_count,
  sum(page_visit_count) AS page_visit_count,
  uniqCombinedArrayState(12)(visited_urls) AS unique_url_count,
  sum(login_path_visit_count) AS login_path_visit_count,
  sum(signup_path_visit_count) AS signup_path_visit_count,
  sum(checkout_path_visit_count) AS checkout_path_visit_count,
  sum(cart_path_visit_count) AS cart_path_visit_count,
  sum(billing_path_visit_count) AS billing_path_visit_count,
  sum(settings_path_visit_count) AS settings_path_visit_count,
  sum(account_path_visit_count) AS account_path_visit_count,
  sum(error_path_visit_count) AS error_path_visit_count,
  sum(not_found_path_visit_count) AS not_found_path_visit_count,
  sum(admin_path_visit_count) AS admin_path_visit_count,
  sum(dashboard_path_visit_count) AS dashboard_path_visit_count,
  sum(onboarding_path_visit_count) AS onboarding_path_visit_count,
  sum(cancel_path_visit_count) AS cancel_path_visit_count,
  sum(refund_path_visit_count) AS refund_path_visit_count,
  sum(console_error_count) AS console_error_count,
  sum(console_error_after_click_count) AS console_error_after_click_count,
  sum(console_warn_count) AS console_warn_count,
  sum(network_request_count) AS network_request_count,
  sum(network_failed_request_count) AS network_failed_request_count,
  sum(network_4xx_count) AS network_4xx_count,
  sum(network_5xx_count) AS network_5xx_count,
  sum(network_request_duration_sum) AS network_request_duration_sum,
  sum(network_request_duration_sum_of_squares) AS network_request_duration_sum_of_squares,
  sum(network_request_duration_count) AS network_request_duration_count,
  sum(mutation_count) AS mutation_count,
  sum(viewport_resize_count) AS viewport_resize_count,
  sum(touch_event_count) AS touch_event_count,
  max(max_scroll_y) AS max_scroll_y,
  uniqCombinedArrayState(12)(click_target_ids) AS unique_click_target_count,
  uniqCombinedArrayState(12)(form_field_ids) AS unique_form_field_count,
  sum(text_selection_count) AS text_selection_count,
  sum(selection_copy_count) AS selection_copy_count,
  max(is_deleted) AS is_deleted
FROM posthog.kafka_session_replay_features
GROUP BY
  session_id, team_id
SQL

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
      type = "DateTime64(6, 'UTC')"
    }
    column "max_last_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "event_count" {
      type = "Int64"
    }
    column "mouse_position_count" {
      type = "Int64"
    }
    column "mouse_sum_x" {
      type = "Float64"
    }
    column "mouse_sum_x_squared" {
      type = "Float64"
    }
    column "mouse_sum_y" {
      type = "Float64"
    }
    column "mouse_sum_y_squared" {
      type = "Float64"
    }
    column "mouse_distance_traveled" {
      type = "Float64"
    }
    column "mouse_direction_change_count" {
      type = "Int64"
    }
    column "mouse_velocity_sum" {
      type = "Float64"
    }
    column "mouse_velocity_sum_of_squares" {
      type = "Float64"
    }
    column "mouse_velocity_count" {
      type = "Int64"
    }
    column "scroll_event_count" {
      type = "Int64"
    }
    column "total_scroll_magnitude" {
      type = "Float64"
    }
    column "scroll_direction_reversal_count" {
      type = "Int64"
    }
    column "rapid_scroll_reversal_count" {
      type = "Int64"
    }
    column "scroll_to_top_count" {
      type = "Int64"
    }
    column "click_count" {
      type = "Int64"
    }
    column "keypress_count" {
      type = "Int64"
    }
    column "mouse_activity_count" {
      type = "Int64"
    }
    column "rage_click_count" {
      type = "Int64"
    }
    column "dead_click_count" {
      type = "Int64"
    }
    column "backspace_count" {
      type = "Int64"
    }
    column "inter_action_gap_count" {
      type = "Int64"
    }
    column "inter_action_gap_sum_ms" {
      type = "Float64"
    }
    column "inter_action_gap_sum_of_squares_ms" {
      type = "Float64"
    }
    column "max_idle_gap_ms" {
      type = "Float64"
    }
    column "long_idle_gap_count" {
      type = "Int64"
    }
    column "quick_back_count" {
      type = "Int64"
    }
    column "page_visit_count" {
      type = "Int64"
    }
    column "unique_url_count" {
      type = "AggregateFunction(uniqCombinedArray(12), Array(String))"
    }
    column "login_path_visit_count" {
      type = "Int64"
    }
    column "signup_path_visit_count" {
      type = "Int64"
    }
    column "checkout_path_visit_count" {
      type = "Int64"
    }
    column "cart_path_visit_count" {
      type = "Int64"
    }
    column "billing_path_visit_count" {
      type = "Int64"
    }
    column "settings_path_visit_count" {
      type = "Int64"
    }
    column "account_path_visit_count" {
      type = "Int64"
    }
    column "error_path_visit_count" {
      type = "Int64"
    }
    column "not_found_path_visit_count" {
      type = "Int64"
    }
    column "admin_path_visit_count" {
      type = "Int64"
    }
    column "dashboard_path_visit_count" {
      type = "Int64"
    }
    column "onboarding_path_visit_count" {
      type = "Int64"
    }
    column "cancel_path_visit_count" {
      type = "Int64"
    }
    column "refund_path_visit_count" {
      type = "Int64"
    }
    column "console_error_count" {
      type = "Int64"
    }
    column "console_error_after_click_count" {
      type = "Int64"
    }
    column "console_warn_count" {
      type = "Int64"
    }
    column "network_request_count" {
      type = "Int64"
    }
    column "network_failed_request_count" {
      type = "Int64"
    }
    column "network_4xx_count" {
      type = "Int64"
    }
    column "network_5xx_count" {
      type = "Int64"
    }
    column "network_request_duration_sum" {
      type = "Float64"
    }
    column "network_request_duration_sum_of_squares" {
      type = "Float64"
    }
    column "network_request_duration_count" {
      type = "Int64"
    }
    column "mutation_count" {
      type = "Int64"
    }
    column "viewport_resize_count" {
      type = "Int64"
    }
    column "touch_event_count" {
      type = "Int64"
    }
    column "max_scroll_y" {
      type = "Float64"
    }
    column "unique_click_target_count" {
      type = "AggregateFunction(uniqCombinedArray(12), Array(Int64))"
    }
    column "unique_form_field_count" {
      type = "AggregateFunction(uniqCombinedArray(12), Array(Int64))"
    }
    column "text_selection_count" {
      type = "Int64"
    }
    column "selection_copy_count" {
      type = "Int64"
    }
    column "is_deleted" {
      type = "UInt8"
    }
  }

  materialized_view "tophog_mv" {
    to_table = "posthog.writable_tophog"
    query    = <<SQL
SELECT
  timestamp,
  metric,
  type,
  key,
  value,
  count,
  pipeline,
  lane,
  labels
FROM posthog.kafka_tophog
SQL

    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "metric" {
      type = "LowCardinality(String)"
    }
    column "type" {
      type = "LowCardinality(String)"
    }
    column "key" {
      type = "Map(LowCardinality(String), String)"
    }
    column "value" {
      type = "Float64"
    }
    column "count" {
      type = "UInt64"
    }
    column "pipeline" {
      type = "LowCardinality(String)"
    }
    column "lane" {
      type = "LowCardinality(String)"
    }
    column "labels" {
      type = "Map(LowCardinality(String), String)"
    }
  }

  materialized_view "tophog_ws_mv" {
    to_table = "posthog.writable_tophog"
    query    = <<SQL
SELECT
  timestamp,
  metric,
  type,
  key,
  value,
  count,
  pipeline,
  lane,
  labels
FROM posthog.kafka_tophog_ws
SQL

    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "metric" {
      type = "LowCardinality(String)"
    }
    column "type" {
      type = "LowCardinality(String)"
    }
    column "key" {
      type = "Map(LowCardinality(String), String)"
    }
    column "value" {
      type = "Float64"
    }
    column "count" {
      type = "UInt64"
    }
    column "pipeline" {
      type = "LowCardinality(String)"
    }
    column "lane" {
      type = "LowCardinality(String)"
    }
    column "labels" {
      type = "Map(LowCardinality(String), String)"
    }
  }
}
