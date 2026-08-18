node "all" {
  macros = {
    hostClusterRole = "data"
    hostClusterType = "online"
    replica         = "ch1"
    shard           = "01"
  }
}

database "posthog" {
  table "kafka_app_metrics" {
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
      type = "Int64"
    }
    column "successes_on_retry" {
      type = "Int64"
    }
    column "failures" {
      type = "Int64"
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
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_app_metrics'"
      group_name  = "kafka_group_name = 'group1'"
      format      = "kafka_format = 'JSONEachRow'"
    }
  }

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

  table "kafka_duplicate_events" {
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "event" {
      type = "String"
    }
    column "source_uuid" {
      type = "UUID"
    }
    column "duplicate_uuid" {
      type = "UUID"
    }
    column "similarity_score" {
      type = "Float64"
    }
    column "dedup_type" {
      type = "LowCardinality(String)"
    }
    column "is_confirmed" {
      type = "UInt8"
    }
    column "reason" {
      type = "Nullable(String)"
    }
    column "version" {
      type = "String"
    }
    column "different_property_count" {
      type = "UInt32"
    }
    column "properties_similarity" {
      type = "Float64"
    }
    column "source_message" {
      type = "String"
    }
    column "duplicate_message" {
      type = "String"
    }
    column "distinct_fields" {
      type = "String"
    }
    column "inserted_at" {
      type = "DateTime64(3, 'UTC')"
    }
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_ingestion_events_duplicates'"
      group_name  = "kafka_group_name = 'clickhouse_duplicate_events'"
      format      = "kafka_format = 'JSONEachRow'"
    }
  }

  table "kafka_error_tracking_issue_fingerprint_overrides" {
    column "team_id" {
      type = "Int64"
    }
    column "fingerprint" {
      type = "String"
    }
    column "issue_id" {
      type = "UUID"
    }
    column "is_deleted" {
      type = "Int8"
    }
    column "version" {
      type = "Int64"
    }
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_error_tracking_issue_fingerprint'"
      group_name  = "kafka_group_name = 'clickhouse-error-tracking-issue-fingerprint-overrides'"
      format      = "kafka_format = 'JSONEachRow'"
    }
  }

  table "kafka_events_dead_letter_queue" {
    column "id" {
      type = "UUID"
    }
    column "event_uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "String"
    }
    column "distinct_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "elements_chain" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "ip" {
      type = "String"
    }
    column "site_url" {
      type = "String"
    }
    column "now" {
      type = "DateTime64(6, 'UTC')"
    }
    column "raw_payload" {
      type = "String"
    }
    column "error_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "error_location" {
      type = "String"
    }
    column "error" {
      type = "String"
    }
    column "tags" {
      type = "Array(String)"
    }
    engine "kafka" {
      broker_list          = "msk_cluster"
      topic_list           = "kafka_topic_list = 'events_dead_letter_queue'"
      group_name           = "kafka_group_name = 'group1'"
      format               = "kafka_format = 'JSONEachRow'"
      skip_broken_messages = 1000
    }
  }

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
    engine "kafka" {
      broker_list          = "msk_cluster"
      topic_list           = "kafka_topic_list = 'clickhouse_events_json'"
      group_name           = "kafka_group_name = 'clickhouse_events_json_native_json'"
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

  table "kafka_groups" {
    column "group_type_index" {
      type = "UInt8"
    }
    column "group_key" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(3)"
    }
    column "team_id" {
      type = "Int64"
    }
    column "group_properties" {
      type = "String"
    }
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_groups'"
      group_name  = "kafka_group_name = 'group1'"
      format      = "kafka_format = 'JSONEachRow'"
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

  table "kafka_ingestion_warnings" {
    column "team_id" {
      type = "Int64"
    }
    column "source" {
      type = "LowCardinality(String)"
    }
    column "type" {
      type = "String"
    }
    column "details" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_ingestion_warnings'"
      group_name  = "kafka_group_name = 'group1'"
      format      = "kafka_format = 'JSONEachRow'"
    }
  }

  table "kafka_log_entries_v3" {
    column "team_id" {
      type = "UInt64"
    }
    column "log_source" {
      type = "LowCardinality(String)"
    }
    column "log_source_id" {
      type = "String"
    }
    column "instance_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "level" {
      type = "LowCardinality(String)"
    }
    column "message" {
      type = "String"
    }
    engine "kafka" {
      broker_list          = "msk_cluster"
      topic_list           = "kafka_topic_list = 'log_entries'"
      group_name           = "kafka_group_name = 'clickhouse_log_entries'"
      format               = "kafka_format = 'JSONEachRow'"
      skip_broken_messages = 100
    }
  }

  table "kafka_log_entries_ws" {
    column "team_id" {
      type = "UInt64"
    }
    column "log_source" {
      type = "LowCardinality(String)"
    }
    column "log_source_id" {
      type = "String"
    }
    column "instance_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "level" {
      type = "LowCardinality(String)"
    }
    column "message" {
      type = "String"
    }
    engine "kafka" {
      broker_list          = "warpstream_ingestion"
      topic_list           = "kafka_topic_list = 'log_entries'"
      group_name           = "kafka_group_name = 'clickhouse_log_entries_ws'"
      format               = "kafka_format = 'JSONEachRow'"
      skip_broken_messages = 100
    }
  }

  table "kafka_person" {
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
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_person'"
      group_name  = "kafka_group_name = 'group1'"
      format      = "kafka_format = 'JSONEachRow'"
    }
  }

  table "kafka_person_distinct_id2" {
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
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_person_distinct_id'"
      group_name  = "kafka_group_name = 'group1'"
      format      = "kafka_format = 'JSONEachRow'"
    }
  }

  table "kafka_person_distinct_id_overrides" {
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
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_person_distinct_id'"
      group_name  = "kafka_group_name = 'clickhouse-person-distinct-id-overrides'"
      format      = "kafka_format = 'JSONEachRow'"
    }
  }

  table "kafka_plugin_log_entries" {
    column "id" {
      type = "UUID"
    }
    column "team_id" {
      type = "Int64"
    }
    column "plugin_id" {
      type = "Int64"
    }
    column "plugin_config_id" {
      type = "Int64"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "source" {
      type = "String"
    }
    column "type" {
      type = "String"
    }
    column "message" {
      type = "String"
    }
    column "instance_id" {
      type = "UUID"
    }
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'plugin_log_entries'"
      group_name  = "kafka_group_name = 'group1'"
      format      = "kafka_format = 'JSONEachRow'"
    }
  }

  table "kafka_posthog_document_embeddings" {
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
      type = "String"
    }
    column "metadata" {
      type = "String"
    }
    column "embedding" {
      type = "Array(Float64)"
    }
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_document_embeddings'"
      group_name  = "kafka_group_name = 'clickhouse_document_embeddings'"
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

  table "kafka_session_replay_events" {
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "first_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "last_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "block_url" {
      type = "Nullable(String)"
    }
    column "first_url" {
      type = "Nullable(String)"
    }
    column "urls" {
      type = "Array(String)"
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
    column "active_milliseconds" {
      type = "Int64"
    }
    column "console_log_count" {
      type = "Int64"
    }
    column "console_warn_count" {
      type = "Int64"
    }
    column "console_error_count" {
      type = "Int64"
    }
    column "size" {
      type = "Int64"
    }
    column "event_count" {
      type = "Int64"
    }
    column "message_count" {
      type = "Int64"
    }
    column "snapshot_source" {
      type = "LowCardinality(Nullable(String))"
    }
    column "snapshot_library" {
      type = "Nullable(String)"
    }
    column "retention_period_days" {
      type = "Nullable(Int64)"
    }
    column "is_deleted" {
      type = "UInt8"
    }
    column "ai_tags_fixed" {
      type = "Array(String)"
    }
    column "ai_tags_freeform" {
      type = "Array(String)"
    }
    column "ai_highlighted" {
      type = "UInt8"
    }
    column "surfacing_score" {
      type = "Nullable(Float32)"
    }
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_session_replay_events'"
      group_name  = "kafka_group_name = 'group1'"
      format      = "kafka_format = 'JSONEachRow'"
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

  table "kafka_usage_report_events_preagg" {
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
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    engine "kafka" {
      broker_list          = "warpstream_ingestion"
      topic_list           = "kafka_topic_list = 'clickhouse_events_json'"
      group_name           = "kafka_group_name = 'clickhouse_usage_report_events_preagg'"
      format               = "kafka_format = 'JSONEachRow'"
      num_consumers        = 1
      skip_broken_messages = 100
      thread_per_consumer  = true
    }
  }

  table "query_log_archive_old" {
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_query_log_archive"
      sharding_key    = "cityHash64(query_id)"
    }
  }

  table "writable_app_metrics" {
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

  table "writable_duplicate_events" {
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "event" {
      type = "String"
    }
    column "source_uuid" {
      type = "UUID"
    }
    column "duplicate_uuid" {
      type = "UUID"
    }
    column "similarity_score" {
      type = "Float64"
    }
    column "dedup_type" {
      type = "LowCardinality(String)"
    }
    column "is_confirmed" {
      type = "UInt8"
    }
    column "reason" {
      type = "Nullable(String)"
    }
    column "version" {
      type = "String"
    }
    column "different_property_count" {
      type = "UInt32"
    }
    column "properties_similarity" {
      type = "Float64"
    }
    column "source_message" {
      type = "String"
    }
    column "duplicate_message" {
      type = "String"
    }
    column "distinct_fields" {
      type = "Array(Tuple(field_name String, original_value String, new_value String))"
    }
    column "inserted_at" {
      type = "DateTime64(3, 'UTC')"
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
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "duplicate_events"
    }
  }

  table "writable_error_tracking_issue_fingerprint_overrides" {
    column "team_id" {
      type = "Int64"
    }
    column "fingerprint" {
      type = "String"
    }
    column "issue_id" {
      type = "UUID"
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
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "error_tracking_issue_fingerprint_overrides"
    }
  }

  table "writable_events_dead_letter_queue" {
    column "id" {
      type = "UUID"
    }
    column "event_uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "String"
    }
    column "distinct_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "elements_chain" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "ip" {
      type = "String"
    }
    column "site_url" {
      type = "String"
    }
    column "now" {
      type = "DateTime64(6, 'UTC')"
    }
    column "raw_payload" {
      type = "String"
    }
    column "error_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "error_location" {
      type = "String"
    }
    column "error" {
      type = "String"
    }
    column "tags" {
      type = "Array(String)"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "events_dead_letter_queue"
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

  table "writable_groups" {
    column "group_type_index" {
      type = "UInt8"
    }
    column "group_key" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(3)"
    }
    column "team_id" {
      type = "Int64"
    }
    column "group_properties" {
      type = "String"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "groups"
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

  table "writable_ingestion_warnings" {
    column "team_id" {
      type = "Int64"
    }
    column "source" {
      type = "LowCardinality(String)"
    }
    column "type" {
      type = "String"
    }
    column "details" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
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
      remote_table    = "sharded_ingestion_warnings"
      sharding_key    = "rand()"
    }
  }

  table "writable_person" {
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
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "person"
    }
  }

  table "writable_person_distinct_id2" {
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
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "person_distinct_id2"
    }
  }

  table "writable_person_distinct_id_overrides" {
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
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "person_distinct_id_overrides"
    }
  }

  table "writable_plugin_log_entries" {
    column "id" {
      type = "UUID"
    }
    column "team_id" {
      type = "Int64"
    }
    column "plugin_id" {
      type = "Int64"
    }
    column "plugin_config_id" {
      type = "Int64"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "source" {
      type = "String"
    }
    column "type" {
      type = "String"
    }
    column "message" {
      type = "String"
    }
    column "instance_id" {
      type = "UUID"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "plugin_log_entries"
    }
  }

  table "writable_posthog_document_embeddings" {
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "partitioned_sharded_posthog_document_embeddings"
      sharding_key    = "cityHash64(document_id)"
    }
  }

  table "writable_posthog_document_embeddings_buffer" {
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_posthog_document_embeddings_buffer"
      sharding_key    = "cityHash64(document_id)"
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

  table "writable_sharded_query_log_archive" {
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_query_log_archive"
      sharding_key    = "cityHash64(query_id)"
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

  table "writable_usage_report_events_preagg" {
    column "date" {
      type = "Date"
    }
    column "team_id" {
      type = "Int64"
    }
    column "person_mode" {
      type = "LowCardinality(String)"
    }
    column "lib" {
      type = "LowCardinality(String)"
    }
    column "event" {
      type = "String"
    }
    column "distinct_events_unique" {
      type = "AggregateFunction(uniqExact, Tuple(UInt64, UInt64, UInt64))"
    }
    column "event_count" {
      type = "AggregateFunction(sum, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_usage_report_events_preagg"
      sharding_key    = "sipHash64(date)"
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

  materialized_view "app_metrics_mv" {
    to_table = "posthog.writable_app_metrics"
    query    = <<SQL
SELECT
  team_id,
  timestamp,
  plugin_config_id,
  category,
  job_id,
  successes,
  successes_on_retry,
  failures,
  error_uuid,
  error_type,
  error_details,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_app_metrics
SQL

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
      type = "Int64"
    }
    column "successes_on_retry" {
      type = "Int64"
    }
    column "failures" {
      type = "Int64"
    }
    column "error_uuid" {
      type = "UUID"
    }
    column "error_type" {
      type = "String"
    }
    column "error_details" {
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

  materialized_view "duplicate_events_mv" {
    to_table = "posthog.writable_duplicate_events"
    query    = <<SQL
SELECT
  team_id,
  distinct_id,
  event,
  source_uuid,
  duplicate_uuid,
  similarity_score,
  dedup_type,
  is_confirmed,
  reason,
  version,
  different_property_count,
  properties_similarity,
  source_message,
  duplicate_message,
  JSONExtract(
    distinct_fields,
    'Array(Tuple(field_name String, original_value String, new_value String))'
  ) AS distinct_fields,
  inserted_at,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_duplicate_events
SQL

    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "event" {
      type = "String"
    }
    column "source_uuid" {
      type = "UUID"
    }
    column "duplicate_uuid" {
      type = "UUID"
    }
    column "similarity_score" {
      type = "Float64"
    }
    column "dedup_type" {
      type = "LowCardinality(String)"
    }
    column "is_confirmed" {
      type = "UInt8"
    }
    column "reason" {
      type = "Nullable(String)"
    }
    column "version" {
      type = "String"
    }
    column "different_property_count" {
      type = "UInt32"
    }
    column "properties_similarity" {
      type = "Float64"
    }
    column "source_message" {
      type = "String"
    }
    column "duplicate_message" {
      type = "String"
    }
    column "distinct_fields" {
      type = "Array(Tuple(field_name String, original_value String, new_value String))"
    }
    column "inserted_at" {
      type = "DateTime64(3, 'UTC')"
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

  materialized_view "error_tracking_issue_fingerprint_overrides_mv" {
    to_table = "posthog.writable_error_tracking_issue_fingerprint_overrides"
    query    = <<SQL
SELECT
  team_id,
  fingerprint,
  issue_id,
  is_deleted,
  version,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_error_tracking_issue_fingerprint_overrides
WHERE version > 0
SQL

    column "team_id" {
      type = "Int64"
    }
    column "fingerprint" {
      type = "String"
    }
    column "issue_id" {
      type = "UUID"
    }
    column "is_deleted" {
      type = "Int8"
    }
    column "version" {
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

  materialized_view "events_dead_letter_queue_mv" {
    to_table = "posthog.writable_events_dead_letter_queue"
    query    = <<SQL
SELECT
  id,
  event_uuid,
  event,
  properties,
  distinct_id,
  team_id,
  elements_chain,
  created_at,
  ip,
  site_url,
  now,
  raw_payload,
  error_timestamp,
  error_location,
  error,
  tags,
  _timestamp,
  _offset
FROM posthog.kafka_events_dead_letter_queue
SQL

    column "id" {
      type = "UUID"
    }
    column "event_uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "String"
    }
    column "distinct_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "elements_chain" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "ip" {
      type = "String"
    }
    column "site_url" {
      type = "String"
    }
    column "now" {
      type = "DateTime64(6, 'UTC')"
    }
    column "raw_payload" {
      type = "String"
    }
    column "error_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "error_location" {
      type = "String"
    }
    column "error" {
      type = "String"
    }
    column "tags" {
      type = "Array(String)"
    }
    column "_timestamp" {
      type = "Nullable(DateTime)"
    }
    column "_offset" {
      type = "UInt64"
    }
  }

  materialized_view "events_json_table_mv" {
    to_table = "posthog.writable_events_json"
    query    = <<SQL
SELECT
  uuid,
  event,
  ifNull(
    accurateCastOrNull(properties, 'JSON'),
    CAST(concat('{"$unparseable_properties":', toJSONString(properties), '}'), 'JSON')
  ) AS properties,
  timestamp,
  team_id,
  distinct_id,
  elements_chain,
  created_at,
  person_id,
  person_created_at,
  ifNull(
    accurateCastOrNull(person_properties, 'JSON'),
    CAST(concat('{"$unparseable_properties":', toJSONString(person_properties), '}'), 'JSON')
  ) AS person_properties,
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
  _timestamp,
  _offset,
  arrayMap(
    i -> (_headers.value[i]),
    arrayFilter(
      i -> ((_headers.name[i]) = 'kafka-consumer-breadcrumbs'),
      arrayEnumerate(_headers.name)
    )
  ) AS consumer_breadcrumbs
FROM posthog.kafka_events_json_native_json
SQL

    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "JSON"
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
      type = "JSON"
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

  materialized_view "groups_mv" {
    to_table = "posthog.writable_groups"
    query    = <<SQL
SELECT
  group_type_index,
  group_key,
  created_at,
  team_id,
  group_properties,
  _timestamp,
  _offset
FROM posthog.kafka_groups
SQL

    column "group_type_index" {
      type = "UInt8"
    }
    column "group_key" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(3)"
    }
    column "team_id" {
      type = "Int64"
    }
    column "group_properties" {
      type = "String"
    }
    column "_timestamp" {
      type = "Nullable(DateTime)"
    }
    column "_offset" {
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

  materialized_view "ingestion_warnings_mv" {
    to_table = "posthog.writable_ingestion_warnings"
    query    = <<SQL
SELECT
  team_id,
  source,
  type,
  details,
  timestamp,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_ingestion_warnings
SQL

    column "team_id" {
      type = "Int64"
    }
    column "source" {
      type = "LowCardinality(String)"
    }
    column "type" {
      type = "String"
    }
    column "details" {
      type = "String"
    }
    column "timestamp" {
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
  }

  materialized_view "log_entries_v3_mv" {
    to_table = "posthog.writable_log_entries"
    query    = <<SQL
SELECT
  team_id,
  log_source,
  log_source_id,
  instance_id,
  timestamp,
  level,
  message,
  _timestamp,
  _offset
FROM posthog.kafka_log_entries_v3
WHERE toDate(timestamp) <= today()
SQL

    column "team_id" {
      type = "UInt64"
    }
    column "log_source" {
      type = "LowCardinality(String)"
    }
    column "log_source_id" {
      type = "String"
    }
    column "instance_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "level" {
      type = "LowCardinality(String)"
    }
    column "message" {
      type = "String"
    }
    column "_timestamp" {
      type = "Nullable(DateTime)"
    }
    column "_offset" {
      type = "UInt64"
    }
  }

  materialized_view "log_entries_ws_mv" {
    to_table = "posthog.writable_log_entries"
    query    = <<SQL
SELECT
  team_id,
  log_source,
  log_source_id,
  instance_id,
  timestamp,
  level,
  message,
  _timestamp,
  _offset
FROM posthog.kafka_log_entries_ws
WHERE toDate(timestamp) <= today()
SQL

    column "team_id" {
      type = "UInt64"
    }
    column "log_source" {
      type = "LowCardinality(String)"
    }
    column "log_source_id" {
      type = "String"
    }
    column "instance_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "level" {
      type = "LowCardinality(String)"
    }
    column "message" {
      type = "String"
    }
    column "_timestamp" {
      type = "Nullable(DateTime)"
    }
    column "_offset" {
      type = "UInt64"
    }
  }

  materialized_view "person_distinct_id2_mv" {
    to_table = "posthog.writable_person_distinct_id2"
    query    = <<SQL
SELECT
  team_id,
  distinct_id,
  person_id,
  is_deleted,
  version,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_person_distinct_id2
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
    column "is_deleted" {
      type = "Int8"
    }
    column "version" {
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

  materialized_view "person_distinct_id_overrides_mv" {
    to_table = "posthog.writable_person_distinct_id_overrides"
    query    = <<SQL
SELECT
  team_id,
  distinct_id,
  person_id,
  is_deleted,
  version,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_person_distinct_id_overrides
WHERE version > 0
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
    column "is_deleted" {
      type = "Int8"
    }
    column "version" {
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

  materialized_view "person_mv" {
    to_table = "posthog.writable_person"
    query    = <<SQL
SELECT
  id,
  created_at,
  team_id,
  properties,
  is_identified,
  is_deleted,
  version,
  last_seen_at,
  _timestamp,
  _offset
FROM posthog.kafka_person
SQL

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
    column "_timestamp" {
      type = "Nullable(DateTime)"
    }
    column "_offset" {
      type = "UInt64"
    }
  }

  materialized_view "plugin_log_entries_mv" {
    to_table = "posthog.writable_plugin_log_entries"
    query    = <<SQL
SELECT
  id,
  team_id,
  plugin_id,
  plugin_config_id,
  timestamp,
  source,
  type,
  message,
  instance_id,
  _timestamp,
  _offset
FROM posthog.kafka_plugin_log_entries
SQL

    column "id" {
      type = "UUID"
    }
    column "team_id" {
      type = "Int64"
    }
    column "plugin_id" {
      type = "Int64"
    }
    column "plugin_config_id" {
      type = "Int64"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "source" {
      type = "String"
    }
    column "type" {
      type = "String"
    }
    column "message" {
      type = "String"
    }
    column "instance_id" {
      type = "UUID"
    }
    column "_timestamp" {
      type = "Nullable(DateTime)"
    }
    column "_offset" {
      type = "UInt64"
    }
  }

  materialized_view "posthog_document_embeddings_kafka_to_buffer_mv" {
    to_table = "posthog.writable_posthog_document_embeddings_buffer"
    query    = <<SQL
SELECT
  team_id,
  product,
  document_type,
  model_name,
  rendering,
  document_id,
  timestamp,
  _timestamp AS inserted_at,
  coalesce(content, '') AS content,
  coalesce(metadata, '{}') AS metadata,
  embedding,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_posthog_document_embeddings
SQL

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
      type = "Nullable(DateTime)"
    }
    column "content" {
      type = "String"
    }
    column "metadata" {
      type = "String"
    }
    column "embedding" {
      type = "Array(Float64)"
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

  materialized_view "session_replay_events_mv" {
    to_table = "posthog.writable_session_replay_events"
    query    = <<SQL
SELECT
  session_id,
  team_id,
  any(distinct_id) AS distinct_id,
  min(first_timestamp) AS min_first_timestamp,
  max(last_timestamp) AS max_last_timestamp,
  groupArray(if(block_url != '', first_timestamp, NULL)) AS block_first_timestamps,
  groupArray(if(block_url != '', last_timestamp, NULL)) AS block_last_timestamps,
  groupArray(block_url) AS block_urls,
  argMinState(first_url, first_timestamp) AS first_url,
  groupUniqArrayArray(urls) AS all_urls,
  sum(click_count) AS click_count,
  sum(keypress_count) AS keypress_count,
  sum(mouse_activity_count) AS mouse_activity_count,
  sum(active_milliseconds) AS active_milliseconds,
  sum(console_log_count) AS console_log_count,
  sum(console_warn_count) AS console_warn_count,
  sum(console_error_count) AS console_error_count,
  sum(size) AS size,
  sum(message_count) AS message_count,
  sum(event_count) AS event_count,
  argMinState(snapshot_source, first_timestamp) AS snapshot_source,
  argMinState(snapshot_library, first_timestamp) AS snapshot_library,
  max(_timestamp) AS _timestamp,
  max(retention_period_days) AS retention_period_days,
  max(is_deleted) AS is_deleted,
  groupUniqArrayArray(ai_tags_fixed) AS ai_tags_fixed,
  groupUniqArrayArray(ai_tags_freeform) AS ai_tags_freeform,
  max(ai_highlighted) AS ai_highlighted,
  max(surfacing_score) AS surfacing_score
FROM posthog.kafka_session_replay_events
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
    column "block_first_timestamps" {
      type = "SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC')))"
    }
    column "block_last_timestamps" {
      type = "SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC')))"
    }
    column "block_urls" {
      type = "SimpleAggregateFunction(groupArrayArray, Array(String))"
    }
    column "first_url" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "all_urls" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
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
    column "active_milliseconds" {
      type = "Int64"
    }
    column "console_log_count" {
      type = "Int64"
    }
    column "console_warn_count" {
      type = "Int64"
    }
    column "console_error_count" {
      type = "Int64"
    }
    column "size" {
      type = "Int64"
    }
    column "message_count" {
      type = "Int64"
    }
    column "event_count" {
      type = "Int64"
    }
    column "snapshot_source" {
      type = "AggregateFunction(argMin, LowCardinality(Nullable(String)), DateTime64(6, 'UTC'))"
    }
    column "snapshot_library" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "_timestamp" {
      type = "Nullable(DateTime)"
    }
    column "retention_period_days" {
      type = "SimpleAggregateFunction(max, Nullable(Int64))"
    }
    column "is_deleted" {
      type = "SimpleAggregateFunction(max, UInt8)"
    }
    column "ai_tags_fixed" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "ai_tags_freeform" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "ai_highlighted" {
      type = "SimpleAggregateFunction(max, UInt8)"
    }
    column "surfacing_score" {
      type = "SimpleAggregateFunction(max, Nullable(Float32))"
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

  materialized_view "usage_report_events_preagg_mv" {
    to_table = "posthog.writable_usage_report_events_preagg"
    query    = <<SQL
SELECT
  toDate(timestamp) AS date,
  team_id,
  person_mode,
  JSONExtractString(properties, '$lib') AS lib,
  event,
  uniqExactState((cityHash64(distinct_id), cityHash64(toString(uuid)), cityHash64(event))) AS distinct_events_unique,
  sumState(toUInt64(1)) AS event_count
FROM posthog.kafka_usage_report_events_preagg
GROUP BY
  date, team_id, person_mode, lib, event
SQL

    column "date" {
      type = "Date"
    }
    column "team_id" {
      type = "Int64"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "lib" {
      type = "String"
    }
    column "event" {
      type = "String"
    }
    column "distinct_events_unique" {
      type = "AggregateFunction(uniqExact, Tuple(UInt64, UInt64, UInt64))"
    }
    column "event_count" {
      type = "AggregateFunction(sum, UInt64)"
    }
  }
}
