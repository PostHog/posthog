node "small" {
  macros = {
    hostClusterRole = "small"
    hostClusterType = "online"
    replica         = "small"
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

  table "kafka_error_tracking_issue_fingerprint_embeddings" {
    column "team_id" {
      type = "Int64"
    }
    column "model_name" {
      type = "LowCardinality(String)"
    }
    column "embedding_version" {
      type = "Int64"
    }
    column "fingerprint" {
      type = "String"
    }
    column "inserted_at" {
      type = "DateTime64(3, 'UTC')"
    }
    column "embeddings" {
      type = "Array(Float64)"
    }
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_error_tracking_issue_fingerprint_embeddings'"
      group_name  = "kafka_group_name = 'clickhouse_error_tracking_fingerprint_embeddings'"
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

  table "writable_error_tracking_issue_fingerprint_embeddings" {
    column "team_id" {
      type = "Int64"
    }
    column "model_name" {
      type = "LowCardinality(String)"
    }
    column "embedding_version" {
      type = "Int64"
    }
    column "fingerprint" {
      type = "String"
    }
    column "inserted_at" {
      type = "DateTime64(3, 'UTC')"
    }
    column "embeddings" {
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
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "error_tracking_issue_fingerprint_embeddings"
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

  materialized_view "error_tracking_issue_fingerprint_embeddings_mv" {
    to_table = "posthog.writable_error_tracking_issue_fingerprint_embeddings"
    query    = <<SQL
SELECT
  team_id,
  model_name,
  embedding_version,
  fingerprint,
  _timestamp AS inserted_at,
  embeddings,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_error_tracking_issue_fingerprint_embeddings
SQL

    column "team_id" {
      type = "Int64"
    }
    column "model_name" {
      type = "LowCardinality(String)"
    }
    column "embedding_version" {
      type = "Int64"
    }
    column "fingerprint" {
      type = "String"
    }
    column "inserted_at" {
      type = "Nullable(DateTime)"
    }
    column "embeddings" {
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

  table "writable_billing_usage_records" {
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
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_billing_usage_records"
      sharding_key    = "cityHash64(team_id)"
    }
  }

  table "kafka_billing_usage_records" {
    settings = { date_time_input_format = "best_effort" }
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
    engine "kafka" {
      broker_list = "warpstream_ingestion"
      topic_list  = "kafka_topic_list = 'clickhouse_billing_usage_records'"
      group_name  = "kafka_group_name = 'clickhouse_billing_usage_records'"
      format      = "kafka_format = 'JSONEachRow'"
    }
  }

  materialized_view "billing_usage_records_mv" {
    to_table = "posthog.writable_billing_usage_records"
    query    = <<SQL
SELECT
  schema_version,
  record_id,
  producer_id,
  team_id,
  organization_id,
  usage_key,
  unit,
  quantity,
  timestamp,
  inserted_at,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_billing_usage_records
SQL

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
  }
}
