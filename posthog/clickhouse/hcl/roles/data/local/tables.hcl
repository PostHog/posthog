database "posthog" {
  # Mirrors the events column set minus events' materialized property columns, with
  # the full properties JSON kept as the source of truth. The typed property columns
  # below carry their DEFAULT expression only on sharded_flag_evaluations; the
  # Distributed proxy repeats them plain, because a Distributed engine computes
  # nothing.
  table "_flag_evaluations_columns" {
    abstract = true
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
    column "$group_0" {
      type    = "String"
      comment = "column_materializer::$group_0"
    }
    column "$group_1" {
      type    = "String"
      comment = "column_materializer::$group_1"
    }
    column "$group_2" {
      type    = "String"
      comment = "column_materializer::$group_2"
    }
    column "$group_3" {
      type    = "String"
      comment = "column_materializer::$group_3"
    }
    column "$group_4" {
      type    = "String"
      comment = "column_materializer::$group_4"
    }
    column "flag_key" {
      type    = "String"
      comment = "column_materializer::properties::$feature_flag"
    }
    column "response" {
      type    = "LowCardinality(String)"
      comment = "column_materializer::properties::$feature_flag_response"
    }
    column "session_id" {
      type    = "String"
      comment = "column_materializer::properties::$session_id"
    }
    column "request_id" {
      type    = "String"
      comment = "column_materializer::properties::$feature_flag_request_id"
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
  table "adhoc_events_deletion" {
    order_by = ["team_id", "uuid"]
    ttl      = "deleted_at + toIntervalMonth(3) WHERE is_deleted = 1"
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int64"
    }
    column "uuid" {
      type = "UUID"
    }
    column "created_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    column "deleted_at" {
      type = "DateTime"
    }
    column "is_deleted" {
      type    = "UInt8"
      default = "0"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path          = "/clickhouse/tables/noshard/posthog.adhoc_events_deletion"
      replica_name      = "{replica}-{shard}"
      version_column    = "deleted_at"
      is_deleted_column = "is_deleted"
    }
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
  table "app_metrics2" {
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
  table "channel_definition" {
    order_by = ["domain", "kind"]
    settings = {
      index_granularity = "8192"
    }
    column "domain" {
      type = "String"
    }
    column "kind" {
      type = "String"
    }
    column "domain_type" {
      type = "Nullable(String)"
    }
    column "type_if_paid" {
      type = "Nullable(String)"
    }
    column "type_if_organic" {
      type = "Nullable(String)"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.channel_definition"
      replica_name = "{replica}-{shard}"
    }
  }
  table "clickhouse_cleanup_deleted_persons" {
    partition_by = "run_id"
    order_by = ["run_id", "team_id", "person_id"]
    ttl      = "created_at + toIntervalDay(14)"
    settings = {
      index_granularity = "8192"
      ttl_only_drop_parts = "1"
    }
    column "run_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "person_id" {
      type = "UUID"
    }
    column "max_version" {
      type = "UInt64"
    }
    column "created_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.clickhouse_cleanup_deleted_persons"
      replica_name   = "{replica}-{shard}"
      version_column = "created_at"
    }
  }
  table "clickhouse_cleanup_orphaned_distinct_ids" {
    partition_by = "run_id"
    order_by = ["run_id", "team_id", "distinct_id"]
    ttl      = "created_at + toIntervalDay(14)"
    settings = {
      index_granularity = "8192"
      ttl_only_drop_parts = "1"
    }
    column "run_id" {
      type = "String"
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
    column "own_tombstone" {
      type = "UInt8"
    }
    column "max_version" {
      type = "Int64"
    }
    column "created_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.clickhouse_cleanup_orphaned_distinct_ids"
      replica_name   = "{replica}-{shard}"
      version_column = "created_at"
    }
  }
  table "clickhouse_cleanup_revived_distinct_ids" {
    partition_by = "run_id"
    order_by = ["run_id", "team_id", "distinct_id"]
    ttl      = "created_at + toIntervalDay(14)"
    settings = {
      index_granularity = "8192"
      ttl_only_drop_parts = "1"
    }
    column "run_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "created_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.clickhouse_cleanup_revived_distinct_ids"
      replica_name   = "{replica}-{shard}"
      version_column = "created_at"
    }
  }
  table "clickhouse_cleanup_revived_persons" {
    partition_by = "run_id"
    order_by = ["run_id", "team_id", "person_id"]
    ttl      = "created_at + toIntervalDay(14)"
    settings = {
      index_granularity = "8192"
      ttl_only_drop_parts = "1"
    }
    column "run_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "person_id" {
      type = "UUID"
    }
    column "created_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.clickhouse_cleanup_revived_persons"
      replica_name   = "{replica}-{shard}"
      version_column = "created_at"
    }
  }
  table "cohort_membership" {
    order_by = ["team_id", "cohort_id", "person_id"]
    settings = {
      index_granularity = "8192"
    }
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.cohort_membership"
      replica_name   = "{replica}-{shard}"
      version_column = "last_updated"
    }
  }
  table "distinct_id_usage" {
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
  table "distributed_events_recent" {
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
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "inserted_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    engine "distributed" {
      cluster_name    = "posthog_primary_replica"
      remote_database = "posthog"
      remote_table    = "sharded_events_recent"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }
  table "distributed_posthog_document_embeddings" {
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
  table "distributed_posthog_document_embeddings_text_embedding_3_large_3072" {
    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
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
      remote_table    = "sharded_posthog_document_embeddings_text_embedding_3_large_3072"
      sharding_key    = "cityHash64(document_id)"
    }
  }
  table "distributed_posthog_document_embeddings_text_embedding_3_small_1536" {
    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
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
      remote_table    = "sharded_posthog_document_embeddings_text_embedding_3_small_1536"
      sharding_key    = "cityHash64(document_id)"
    }
  }
  table "distributed_system_processes" {
    settings = {
      skip_unavailable_shards = "1"
    }
    column "is_initial_query" {
      type = "UInt8"
    }
    column "user" {
      type = "String"
    }
    column "query_id" {
      type = "String"
    }
    column "address" {
      type = "IPv6"
    }
    column "port" {
      type = "UInt16"
    }
    column "initial_user" {
      type = "String"
    }
    column "initial_query_id" {
      type = "String"
    }
    column "initial_address" {
      type = "IPv6"
    }
    column "initial_port" {
      type = "UInt16"
    }
    column "interface" {
      type = "UInt8"
    }
    column "os_user" {
      type = "String"
    }
    column "client_hostname" {
      type = "String"
    }
    column "client_name" {
      type = "String"
    }
    column "client_agent" {
      type = "LowCardinality(String)"
    }
    column "client_revision" {
      type = "UInt64"
    }
    column "client_version_major" {
      type = "UInt64"
    }
    column "client_version_minor" {
      type = "UInt64"
    }
    column "client_version_patch" {
      type = "UInt64"
    }
    column "client_agent" {
      type = "LowCardinality(String)"
    }
    column "http_method" {
      type = "UInt8"
    }
    column "http_user_agent" {
      type = "String"
    }
    column "http_referer" {
      type = "String"
    }
    column "forwarded_for" {
      type = "String"
    }
    column "quota_key" {
      type = "String"
    }
    column "distributed_depth" {
      type = "UInt64"
    }
    column "elapsed" {
      type = "Float64"
    }
    column "is_cancelled" {
      type = "UInt8"
    }
    column "is_all_data_sent" {
      type = "UInt8"
    }
    column "read_rows" {
      type = "UInt64"
    }
    column "read_bytes" {
      type = "UInt64"
    }
    column "total_rows_approx" {
      type = "UInt64"
    }
    column "written_rows" {
      type = "UInt64"
    }
    column "written_bytes" {
      type = "UInt64"
    }
    column "memory_usage" {
      type = "Int64"
    }
    column "peak_memory_usage" {
      type = "Int64"
    }
    column "query" {
      type = "String"
    }
    column "normalized_query_hash" {
      type = "UInt64"
    }
    column "query_kind" {
      type = "String"
    }
    column "thread_ids" {
      type = "Array(UInt64)"
    }
    column "peak_threads_usage" {
      type = "UInt64"
    }
    column "ProfileEvents" {
      type = "Map(LowCardinality(String), UInt64)"
    }
    column "Settings" {
      type = "Map(LowCardinality(String), LowCardinality(String))"
    }
    column "current_database" {
      type = "String"
    }
    column "is_internal" {
      type = "UInt8"
    }
    column "ProfileEvents.Names" {
      type  = "Array(String)"
      alias = "mapKeys(ProfileEvents)"
    }
    column "ProfileEvents.Values" {
      type  = "Array(UInt64)"
      alias = "mapValues(ProfileEvents)"
    }
    column "Settings.Names" {
      type  = "Array(String)"
      alias = "mapKeys(Settings)"
    }
    column "Settings.Values" {
      type  = "Array(String)"
      alias = "mapValues(Settings)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "system"
      remote_table    = "processes"
    }
  }
  table "duplicate_events" {
    order_by     = ["team_id", "distinct_id", "event", "inserted_at"]
    partition_by = "toYYYYMMDD(inserted_at)"
    ttl          = "inserted_at + toIntervalDay(7)"
    settings = {
      index_granularity = "512"
    }
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
    index "kafka_timestamp_minmax_duplicate_events" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.duplicate_events"
      replica_name = "{replica}-{shard}"
    }
  }
  table "error_tracking_issue_fingerprint_overrides" {
    order_by = ["team_id", "fingerprint"]
    settings = {
      index_granularity = "512"
    }
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
    index "kafka_timestamp_minmax_error_tracking_issue_fingerprint_overrides" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.error_tracking_issue_fingerprint_overrides"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }
  table "events_json" {
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
    order_by     = ["team_id", "toDate(timestamp)", "event", "cityHash64(distinct_id)", "distinct_id", "timestamp", "uuid"]
    partition_by = "clamp(toYYYYMM(timestamp), 202001, 203512)"
    primary_key  = ["team_id", "toDate(timestamp)", "event", "cityHash64(distinct_id)"]
    sample_by    = "cityHash64(distinct_id)"
    settings = {
      index_granularity                                             = "8192"
      enable_block_number_column                                    = "1"
      enable_block_offset_column                                    = "1"
      map_serialization_version                                     = "with_buckets"
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

  table "events_dead_letter_queue" {
    order_by = ["id", "event_uuid", "distinct_id", "team_id"]
    ttl      = "toDate(_timestamp) + toIntervalWeek(4)"
    settings = {
      index_granularity = "512"
    }
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
    index "kafka_timestamp_minmax_events_dead_letter_queue" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.events_dead_letter_queue"
      replica_name   = "{replica}-{shard}"
      version_column = "_timestamp"
    }
  }
  table "exchange_rate" {
    order_by = ["date", "currency"]
    settings = {
      index_granularity = "8192"
    }
    column "currency" {
      type = "String"
    }
    column "date" {
      type = "Date"
    }
    column "rate" {
      type = "Decimal(18, 10)"
    }
    column "version" {
      type    = "UInt32"
      default = "toUnixTimestamp(now())"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.exchange_rate"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }
  table "experiment_exposures_preaggregated" {
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "entity_id" {
      type = "String"
    }
    column "variant" {
      type = "String"
    }
    column "first_exposure_time" {
      type = "DateTime64(6, 'UTC')"
    }
    column "last_exposure_time" {
      type = "DateTime64(6, 'UTC')"
    }
    column "exposure_event_uuid" {
      type = "UUID"
    }
    column "exposure_session_id" {
      type = "String"
    }
    column "breakdown_value" {
      type = "Array(String)"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "Date"
      default = "today() + toIntervalDay(7)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_experiment_exposures_preaggregated"
      sharding_key    = "cityHash64(entity_id)"
    }
  }
  table "flag_evaluations" {
    extend = "_flag_evaluations_columns"
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_flag_evaluations"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }
  table "groups" {
    order_by = ["team_id", "group_type_index", "group_key"]
    settings = {
      index_granularity = "8192"
    }
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
    column "is_deleted" {
      type = "Bool"
    }
    index "is_deleted_idx" {
      expr        = "(is_deleted)"
      type        = "minmax"
      granularity = 1
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.groups"
      replica_name   = "{replica}-{shard}"
      version_column = "_timestamp"
    }
  }
  table "heatmaps" {
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
  table "ingestion_warnings" {
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
      broker_list          = "msk_cluster"
      topic_list           = "kafka_topic_list = 'clickhouse_events_json'"
      group_name           = "kafka_group_name = 'group1'"
      format               = "kafka_format = 'JSONEachRow'"
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
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_performance_events'"
      group_name  = "kafka_group_name = 'group1'"
      format      = "kafka_format = 'JSONEachRow'"
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
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_person_unique_id'"
      group_name  = "kafka_group_name = 'group1'"
      format      = "kafka_format = 'JSONEachRow'"
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
  table "llma_metrics_daily" {
    order_by     = ["team_id", "date", "metric_name"]
    partition_by = "toYYYYMM(date)"
    settings = {
      index_granularity = "8192"
    }
    column "date" {
      type = "Date"
    }
    column "team_id" {
      type = "UInt64"
    }
    column "metric_name" {
      type = "String"
    }
    column "metric_value" {
      type = "Float64"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.llma_metrics_daily"
      replica_name = "{replica}-{shard}"
    }
  }
  table "log_entries" {
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
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_log_entries"
      sharding_key    = "rand()"
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
  table "performance_events" {
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
      remote_table    = "sharded_performance_events"
      sharding_key    = "sipHash64(session_id)"
    }
  }
  table "person_distinct_id" {
    order_by = ["team_id", "distinct_id", "person_id"]
    settings = {
      index_granularity = "8192"
    }
    column "distinct_id" {
      type    = "String"
      comment = "skip_0003_fill_person_distinct_id2"
    }
    column "person_id" {
      type = "UUID"
    }
    column "team_id" {
      type = "Int64"
    }
    column "_sign" {
      type    = "Int8"
      default = "1"
    }
    column "is_deleted" {
      type  = "Int8"
      alias = "if(_sign = -1, 1, 0)"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "replicated_collapsing_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.person_distinct_id"
      replica_name = "{replica}-{shard}"
      sign_column  = "_sign"
    }
  }
  table "person_overrides" {
    order_by     = ["team_id", "old_person_id"]
    partition_by = "toYYYYMM(oldest_event)"
    settings = {
      index_granularity = "8192"
    }
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
    column "created_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "version" {
      type = "Int32"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.person_overrides"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }
  table "pg_embeddings" {
    order_by = ["team_id", "domain", "id"]
    settings = {
      index_granularity = "512"
    }
    column "domain" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "id" {
      type = "String"
    }
    column "vector" {
      type = "Array(Float32)"
    }
    column "text" {
      type = "String"
    }
    column "properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "timestamp" {
      type    = "DateTime64(6, 'UTC')"
      default = "now('UTC')"
    }
    column "is_deleted" {
      type = "UInt8"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path          = "/clickhouse/tables/noshard/posthog.pg_embeddings"
      replica_name      = "{replica}-{shard}"
      version_column    = "timestamp"
      is_deleted_column = "is_deleted"
    }
  }
  table "plugin_log_entries" {
    order_by     = ["team_id", "plugin_id", "plugin_config_id", "timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalWeek(1)"
    settings = {
      index_granularity = "512"
    }
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.plugin_log_entries"
      replica_name   = "{replica}-{shard}"
      version_column = "_timestamp"
    }
  }
  table "preaggregation_results" {
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "time_window_start" {
      type = "DateTime64(6, 'UTC')"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
    column "breakdown_value" {
      type = "Array(String)"
    }
    column "uniq_exact_state" {
      type = "AggregateFunction(uniqExact, UUID)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_preaggregation_results"
      sharding_key    = "sipHash64(job_id)"
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
  table "property_definitions" {
    order_by = ["team_id", "type", "coalesce(event, '')", "name", "coalesce(group_type_index, 255)"]
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "UInt32"
    }
    column "project_id" {
      type = "Nullable(UInt32)"
    }
    column "name" {
      type = "String"
    }
    column "property_type" {
      type = "Nullable(String)"
    }
    column "event" {
      type = "Nullable(String)"
    }
    column "group_type_index" {
      type = "Nullable(UInt8)"
    }
    column "type" {
      type    = "UInt8"
      default = "1"
    }
    column "last_seen_at" {
      type = "DateTime"
    }
    column "version" {
      type         = "UInt64"
      materialized = "(bitShiftLeft(toUInt64(NOT isNull(property_type)), 48) + toUInt64(toUnixTimestamp(last_seen_at)))"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.property_definitions"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
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
  table "raw_sessions_v3" {
    column "team_id" {
      type = "Int64"
    }
    column "session_id_v7" {
      type = "UInt128"
    }
    column "session_timestamp" {
      type         = "DateTime64(3)"
      materialized = "fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80)))"
    }
    column "distinct_id" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "distinct_ids" {
      type = "AggregateFunction(groupUniqArray, String)"
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
      type = "SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String))"
    }
    column "entry_url" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "end_url" {
      type = "AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "last_external_click_url" {
      type = "AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "browser" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "browser_version" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "os" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "os_version" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "device_type" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "viewport_width" {
      type = "AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC'))"
    }
    column "viewport_height" {
      type = "AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC'))"
    }
    column "geoip_country_code" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_subdivision_1_code" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_subdivision_1_name" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_subdivision_city_name" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_time_zone" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_referring_domain" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_source" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_campaign" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_medium" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_term" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_content" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_gclid" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_gad_source" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_fbclid" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_has_gclid" {
      type = "AggregateFunction(argMin, Bool, DateTime64(6, 'UTC'))"
    }
    column "entry_has_fbclid" {
      type = "AggregateFunction(argMin, Bool, DateTime64(6, 'UTC'))"
    }
    column "entry_ad_ids_map" {
      type = "AggregateFunction(argMin, Map(String, String), DateTime64(6, 'UTC'))"
    }
    column "entry_ad_ids_set" {
      type = "AggregateFunction(argMin, Array(String), DateTime64(6, 'UTC'))"
    }
    column "entry_channel_type_properties" {
      type = "AggregateFunction(argMin, Tuple(Nullable(String), Nullable(String), Nullable(String), Nullable(String), Bool, Bool, Nullable(String)), DateTime64(6, 'UTC'))"
    }
    column "pageview_uniq" {
      type = "AggregateFunction(uniqExact, Nullable(UUID))"
    }
    column "autocapture_uniq" {
      type = "AggregateFunction(uniqExact, Nullable(UUID))"
    }
    column "screen_uniq" {
      type = "AggregateFunction(uniqExact, Nullable(UUID))"
    }
    column "page_screen_uniq_up_to" {
      type = "AggregateFunction(uniqUpTo(1), Nullable(UUID))"
    }
    column "has_autocapture" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "flag_values" {
      type = "AggregateFunction(groupUniqArrayMap, Map(String, String))"
    }
    column "flag_keys" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "event_names" {
      type = "SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String))"
    }
    column "hosts" {
      type = "SimpleAggregateFunction(groupUniqArrayArray(100), Array(String))"
    }
    column "emails" {
      type = "SimpleAggregateFunction(groupUniqArrayArray(10), Array(String))"
    }
    column "has_replay_events" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_raw_sessions_v3"
      sharding_key    = "cityHash64(session_id_v7)"
    }
  }
  table "session_replay_embeddings" {
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "embeddings" {
      type = "Array(Float32)"
    }
    column "generation_timestamp" {
      type    = "DateTime64(6, 'UTC')"
      default = "now('UTC')"
    }
    column "source_type" {
      type = "LowCardinality(String)"
    }
    column "input" {
      type = "String"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_session_replay_embeddings"
      sharding_key    = "sipHash64(session_id)"
    }
  }
  table "session_replay_events" {
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
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "keypress_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "mouse_activity_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "active_milliseconds" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "console_log_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "console_warn_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "console_error_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "size" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "message_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "event_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "snapshot_source" {
      type = "AggregateFunction(argMin, LowCardinality(Nullable(String)), DateTime64(6, 'UTC'))"
    }
    column "snapshot_library" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime)"
    }
    column "is_deleted" {
      type    = "SimpleAggregateFunction(max, UInt8)"
      default = "0"
    }
    column "ai_tags_fixed" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "ai_tags_freeform" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "ai_highlighted" {
      type    = "SimpleAggregateFunction(max, UInt8)"
      default = "0"
    }
    column "surfacing_score" {
      type = "SimpleAggregateFunction(max, Nullable(Float32))"
    }
    column "retention_period_days" {
      type = "SimpleAggregateFunction(max, Nullable(Int64))"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_session_replay_events"
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
  table "sharded_app_metrics2" {
    order_by     = ["team_id", "app_source", "app_source_id", "instance_id", "toStartOfHour(timestamp)", "metric_kind", "metric_name"]
    partition_by = "toYYYYMM(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalDay(90)"
    settings = {
      index_granularity = "8192"
    }
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
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.sharded_app_metrics2"
      replica_name = "{replica}"
    }
  }
  table "sharded_distinct_id_usage" {
    order_by     = ["team_id", "minute", "distinct_id"]
    partition_by = "toYYYYMMDD(minute)"
    ttl          = "toDate(minute) + toIntervalDay(7)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
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
    engine "replicated_summing_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.distinct_id_usage"
      replica_name = "{replica}"
      sum_columns  = ["event_count"]
    }
  }
  table "sharded_experiment_exposures_preaggregated" {
    order_by     = ["team_id", "job_id", "entity_id", "breakdown_value"]
    partition_by = "toYYYYMMDD(expires_at)"
    ttl          = "expires_at"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "entity_id" {
      type = "String"
    }
    column "variant" {
      type = "String"
    }
    column "first_exposure_time" {
      type = "DateTime64(6, 'UTC')"
    }
    column "last_exposure_time" {
      type = "DateTime64(6, 'UTC')"
    }
    column "exposure_event_uuid" {
      type = "UUID"
    }
    column "exposure_session_id" {
      type = "String"
    }
    column "breakdown_value" {
      type = "Array(String)"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "Date"
      default = "today() + toIntervalDay(7)"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.experiment_exposures_preaggregated"
      replica_name   = "{replica}"
      version_column = "computed_at"
    }
  }
  table "sharded_flag_evaluations" {
    order_by     = ["team_id", "flag_key", "toDate(timestamp)", "cityHash64(distinct_id)"]
    partition_by = "toYYYYMM(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalDay(90)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    extend = "_flag_evaluations_columns"
    patch_column "$group_0" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), '^\"|\"$', '')"
    }
    patch_column "$group_1" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_1'), '^\"|\"$', '')"
    }
    patch_column "$group_2" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_2'), '^\"|\"$', '')"
    }
    patch_column "$group_3" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_3'), '^\"|\"$', '')"
    }
    patch_column "$group_4" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_4'), '^\"|\"$', '')"
    }
    patch_column "flag_key" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag'), '^\"|\"$', '')"
    }
    patch_column "response" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag_response'), '^\"|\"$', '')"
    }
    patch_column "session_id" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$session_id'), '^\"|\"$', '')"
    }
    patch_column "request_id" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag_request_id'), '^\"|\"$', '')"
    }
    index "distinct_id_idx" {
      expr        = "distinct_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "person_id_idx" {
      expr        = "person_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "session_id_idx" {
      expr        = "session_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "request_id_idx" {
      expr        = "request_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "inserted_at_idx" {
      expr        = "inserted_at"
      type        = "minmax"
      granularity = 1
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.flag_evaluations"
      replica_name = "{replica}"
    }
  }
  table "sharded_heatmaps" {
    order_by     = ["type", "team_id", "toDate(timestamp)", "current_url", "viewport_width"]
    partition_by = "toYYYYMM(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalDay(90)"
    settings = {
      index_granularity = "8192"
    }
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
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.heatmaps"
      replica_name = "{replica}"
    }
  }
  table "sharded_log_entries" {
    order_by     = ["team_id", "log_source", "log_source_id", "instance_id", "timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalDay(90)"
    settings = {
      index_granularity   = "1024"
      ttl_only_drop_parts = "1"
    }
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
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.sharded_log_entries"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }
  table "sharded_performance_events" {
    order_by     = ["team_id", "toDate(timestamp)", "session_id", "pageview_id", "timestamp"]
    partition_by = "toYYYYMM(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalWeek(3)"
    settings = {
      index_granularity = "8192"
    }
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
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_partition" {
      type = "UInt64"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.performance_events"
      replica_name = "{replica}"
    }
  }
  table "sharded_posthog_document_embeddings_buffer" {
    order_by     = ["inserted_at", "model_name", "cityHash64(document_id)"]
    partition_by = "toDate(inserted_at)"
    ttl          = "inserted_at + toIntervalDay(1)"
    settings = {
      index_granularity   = "8192"
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.sharded_posthog_document_embeddings_buffer"
      replica_name   = "{replica}"
      version_column = "inserted_at"
    }
  }
  table "sharded_posthog_document_embeddings_text_embedding_3_large_3072" {
    order_by     = ["team_id", "toDate(timestamp)", "product", "document_type", "rendering", "cityHash64(document_id)"]
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
    index "kafka_timestamp_minmax_sharded_posthog_document_embeddings_text_embedding_3_large_3072" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    index "embedding_idx_l2" {
      expr        = "embedding"
      type        = "vector_similarity('hnsw', 'L2Distance', 3072)"
      granularity = 100000000
    }
    index "embedding_idx_cosine" {
      expr        = "embedding"
      type        = "vector_similarity('hnsw', 'cosineDistance', 3072)"
      granularity = 100000000
    }
    constraint "embedding_dimension_check" {
      check = "length(embedding) = 3072"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.sharded_posthog_document_embeddings_text_embedding_3_large_3072"
      replica_name   = "{replica}"
      version_column = "inserted_at"
    }
  }
  table "sharded_posthog_document_embeddings_text_embedding_3_small_1536" {
    order_by     = ["team_id", "toDate(timestamp)", "product", "document_type", "rendering", "cityHash64(document_id)"]
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
    index "kafka_timestamp_minmax_sharded_posthog_document_embeddings_text_embedding_3_small_1536" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    index "embedding_idx_l2" {
      expr        = "embedding"
      type        = "vector_similarity('hnsw', 'L2Distance', 1536)"
      granularity = 100000000
    }
    index "embedding_idx_cosine" {
      expr        = "embedding"
      type        = "vector_similarity('hnsw', 'cosineDistance', 1536)"
      granularity = 100000000
    }
    constraint "embedding_dimension_check" {
      check = "length(embedding) = 1536"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.sharded_posthog_document_embeddings_text_embedding_3_small_1536"
      replica_name   = "{replica}"
      version_column = "inserted_at"
    }
  }
  table "sharded_preaggregation_results" {
    order_by     = ["team_id", "job_id", "time_window_start", "breakdown_value"]
    partition_by = "toYYYYMM(time_window_start)"
    ttl          = "expires_at"
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "time_window_start" {
      type = "DateTime64(6, 'UTC')"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
    column "breakdown_value" {
      type = "Array(String)"
    }
    column "uniq_exact_state" {
      type = "AggregateFunction(uniqExact, UUID)"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.preaggregation_results"
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
  table "sharded_raw_sessions_v3" {
    order_by     = ["team_id", "session_timestamp", "session_id_v7"]
    partition_by = "toYYYYMM(session_timestamp)"
    settings = {
      index_granularity     = "8192"
      max_delay_to_insert   = "10"
      parts_to_delay_insert = "250"
      parts_to_throw_insert = "1000"
    }
    column "team_id" {
      type = "Int64"
    }
    column "session_id_v7" {
      type = "UInt128"
    }
    column "session_timestamp" {
      type    = "DateTime64(3)"
      default = "fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80)))"
    }
    column "distinct_id" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "distinct_ids" {
      type = "AggregateFunction(groupUniqArray, String)"
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
      type = "SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String))"
    }
    column "entry_url" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "end_url" {
      type = "AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "last_external_click_url" {
      type = "AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "browser" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "browser_version" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "os" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "os_version" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "device_type" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "viewport_width" {
      type = "AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC'))"
    }
    column "viewport_height" {
      type = "AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC'))"
    }
    column "geoip_country_code" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_subdivision_1_code" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_subdivision_1_name" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_subdivision_city_name" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_time_zone" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_referring_domain" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_source" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_campaign" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_medium" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_term" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_content" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_gclid" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_gad_source" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_fbclid" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_has_gclid" {
      type = "AggregateFunction(argMin, Bool, DateTime64(6, 'UTC'))"
    }
    column "entry_has_fbclid" {
      type = "AggregateFunction(argMin, Bool, DateTime64(6, 'UTC'))"
    }
    column "entry_ad_ids_map" {
      type = "AggregateFunction(argMin, Map(String, String), DateTime64(6, 'UTC'))"
    }
    column "entry_ad_ids_set" {
      type = "AggregateFunction(argMin, Array(String), DateTime64(6, 'UTC'))"
    }
    column "entry_channel_type_properties" {
      type = "AggregateFunction(argMin, Tuple(Nullable(String), Nullable(String), Nullable(String), Nullable(String), Bool, Bool, Nullable(String)), DateTime64(6, 'UTC'))"
    }
    column "pageview_uniq" {
      type = "AggregateFunction(uniqExact, Nullable(UUID))"
    }
    column "autocapture_uniq" {
      type = "AggregateFunction(uniqExact, Nullable(UUID))"
    }
    column "screen_uniq" {
      type = "AggregateFunction(uniqExact, Nullable(UUID))"
    }
    column "page_screen_uniq_up_to" {
      type = "AggregateFunction(uniqUpTo(1), Nullable(UUID))"
    }
    column "has_autocapture" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "flag_values" {
      type = "AggregateFunction(groupUniqArrayMap, Map(String, String))"
    }
    column "flag_keys" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "event_names" {
      type = "SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String))"
    }
    column "hosts" {
      type = "SimpleAggregateFunction(groupUniqArrayArray(100), Array(String))"
    }
    column "emails" {
      type = "SimpleAggregateFunction(groupUniqArrayArray(10), Array(String))"
    }
    column "has_replay_events" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    index "event_names_bloom_filter" {
      expr        = "event_names"
      type        = "bloom_filter()"
      granularity = 1
    }
    index "flag_keys_bloom_filter" {
      expr        = "flag_keys"
      type        = "bloom_filter()"
      granularity = 1
    }
    index "hosts_bloom_filter" {
      expr        = "hosts"
      type        = "bloom_filter()"
      granularity = 1
    }
    index "emails_bloom_filter" {
      expr        = "emails"
      type        = "bloom_filter()"
      granularity = 1
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.raw_sessions_v3"
      replica_name = "{replica}"
    }
  }
  table "sharded_session_replay_embeddings" {
    order_by     = ["toDate(generation_timestamp)", "team_id", "session_id"]
    partition_by = "toYYYYMM(generation_timestamp)"
    ttl          = "toDate(generation_timestamp) + toIntervalYear(1)"
    settings = {
      index_granularity = "512"
    }
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "embeddings" {
      type = "Array(Float32)"
    }
    column "generation_timestamp" {
      type    = "DateTime64(6, 'UTC')"
      default = "now('UTC')"
    }
    column "source_type" {
      type = "LowCardinality(String)"
    }
    column "input" {
      type = "String"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.session_replay_embeddings"
      replica_name = "{replica}"
    }
  }
  table "sharded_session_replay_events" {
    order_by     = ["toDate(min_first_timestamp)", "team_id", "session_id"]
    partition_by = "toYYYYMM(min_first_timestamp)"
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
      type = "String"
    }
    column "min_first_timestamp" {
      type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))"
    }
    column "max_last_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
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
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "keypress_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "mouse_activity_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "active_milliseconds" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "console_log_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "console_warn_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "console_error_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "size" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "message_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "event_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "snapshot_source" {
      type = "AggregateFunction(argMin, LowCardinality(Nullable(String)), DateTime64(6, 'UTC'))"
    }
    column "snapshot_library" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime)"
    }
    column "is_deleted" {
      type    = "SimpleAggregateFunction(max, UInt8)"
      default = "0"
    }
    column "ai_tags_fixed" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "ai_tags_freeform" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "ai_highlighted" {
      type    = "SimpleAggregateFunction(max, UInt8)"
      default = "0"
    }
    column "surfacing_score" {
      type = "SimpleAggregateFunction(max, Nullable(Float32))"
    }
    column "retention_period_days" {
      type = "SimpleAggregateFunction(max, Nullable(Int64))"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.session_replay_events"
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
  table "tophog" {
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
  table "usage_report_events_preagg" {
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
  table "web_overview_preaggregated" {
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "time_window_start" {
      type = "DateTime64(6, 'UTC')"
    }
    column "uniq_users_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "uniq_sessions_state" {
      type = "AggregateFunction(uniq, String)"
    }
    column "sum_pageviews_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "avg_duration_state" {
      type = "AggregateFunction(avg, Float64)"
    }
    column "avg_bounce_state" {
      type = "AggregateFunction(avg, Int64)"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_overview_preaggregated"
      sharding_key    = "sipHash64(job_id)"
    }
  }
  table "web_pre_aggregated_bounces" {
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
      zoo_path     = "/clickhouse/tables/noshard/posthog.web_pre_aggregated_bounces"
      replica_name = "{replica}-{shard}"
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
  table "web_pre_aggregated_stats" {
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
      zoo_path     = "/clickhouse/tables/noshard/posthog.web_pre_aggregated_stats"
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
  table "web_stats_paths_preaggregated" {
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
    column "uniq_users_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sum_pageviews_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "avg_bounce_state" {
      type = "AggregateFunction(avg, Nullable(Float64))"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_stats_paths_preaggregated"
      sharding_key    = "sipHash64(job_id)"
    }
  }
  table "web_stats_paths_preaggregated_pathkey" {
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
    column "uniq_users_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sum_pageviews_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "avg_bounce_state" {
      type = "AggregateFunction(avg, Nullable(Float64))"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_stats_paths_preaggregated_pathkey"
      sharding_key    = "sipHash64(breakdown_value)"
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
  table "writable_posthog_document_embeddings_text_embedding_3_large_3072" {
    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
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
      remote_table    = "sharded_posthog_document_embeddings_text_embedding_3_large_3072"
      sharding_key    = "cityHash64(document_id)"
    }
  }
  table "writable_posthog_document_embeddings_text_embedding_3_small_1536" {
    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
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
      remote_table    = "sharded_posthog_document_embeddings_text_embedding_3_small_1536"
      sharding_key    = "cityHash64(document_id)"
    }
  }
  table "writable_raw_sessions" {
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_raw_sessions"
      sharding_key    = "cityHash64(session_id_v7)"
    }
  }
  table "writable_raw_sessions_v3" {
    column "team_id" {
      type = "Int64"
    }
    column "session_id_v7" {
      type = "UInt128"
    }
    column "session_timestamp" {
      type    = "DateTime64(3)"
      default = "fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80)))"
    }
    column "distinct_id" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "distinct_ids" {
      type = "AggregateFunction(groupUniqArray, String)"
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
      type = "SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String))"
    }
    column "entry_url" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "end_url" {
      type = "AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "last_external_click_url" {
      type = "AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "browser" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "browser_version" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "os" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "os_version" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "device_type" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "viewport_width" {
      type = "AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC'))"
    }
    column "viewport_height" {
      type = "AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC'))"
    }
    column "geoip_country_code" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_subdivision_1_code" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_subdivision_1_name" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_subdivision_city_name" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "geoip_time_zone" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_referring_domain" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_source" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_campaign" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_medium" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_term" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_utm_content" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_gclid" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_gad_source" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_fbclid" {
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
    }
    column "entry_has_gclid" {
      type = "AggregateFunction(argMin, Bool, DateTime64(6, 'UTC'))"
    }
    column "entry_has_fbclid" {
      type = "AggregateFunction(argMin, Bool, DateTime64(6, 'UTC'))"
    }
    column "entry_ad_ids_map" {
      type = "AggregateFunction(argMin, Map(String, String), DateTime64(6, 'UTC'))"
    }
    column "entry_ad_ids_set" {
      type = "AggregateFunction(argMin, Array(String), DateTime64(6, 'UTC'))"
    }
    column "entry_channel_type_properties" {
      type = "AggregateFunction(argMin, Tuple(Nullable(String), Nullable(String), Nullable(String), Nullable(String), Bool, Bool, Nullable(String)), DateTime64(6, 'UTC'))"
    }
    column "pageview_uniq" {
      type = "AggregateFunction(uniqExact, Nullable(UUID))"
    }
    column "autocapture_uniq" {
      type = "AggregateFunction(uniqExact, Nullable(UUID))"
    }
    column "screen_uniq" {
      type = "AggregateFunction(uniqExact, Nullable(UUID))"
    }
    column "page_screen_uniq_up_to" {
      type = "AggregateFunction(uniqUpTo(1), Nullable(UUID))"
    }
    column "has_autocapture" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "flag_values" {
      type = "AggregateFunction(groupUniqArrayMap, Map(String, String))"
    }
    column "flag_keys" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "event_names" {
      type = "SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String))"
    }
    column "hosts" {
      type = "SimpleAggregateFunction(groupUniqArrayArray(100), Array(String))"
    }
    column "emails" {
      type = "SimpleAggregateFunction(groupUniqArrayArray(10), Array(String))"
    }
    column "has_replay_events" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_raw_sessions_v3"
      sharding_key    = "cityHash64(session_id_v7)"
    }
  }
  table "writable_session_replay_embeddings" {
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "embeddings" {
      type = "Array(Float32)"
    }
    column "generation_timestamp" {
      type    = "DateTime64(6, 'UTC')"
      default = "now('UTC')"
    }
    column "source_type" {
      type = "LowCardinality(String)"
    }
    column "input" {
      type = "String"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_session_replay_embeddings"
      sharding_key    = "sipHash64(session_id)"
    }
  }
  table "writable_sessions" {
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_sessions"
      sharding_key    = "sipHash64(session_id)"
    }
  }
  table "writeable_performance_events" {
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
      remote_table    = "sharded_performance_events"
      sharding_key    = "sipHash64(session_id)"
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
  materialized_view "posthog_document_embeddings_text_embedding_3_large_3072_mv" {
    to_table = "posthog.writable_posthog_document_embeddings_text_embedding_3_large_3072"
    query    = file("sql/posthog_document_embeddings_text_embedding_3_large_3072_mv.sql")

    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
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
  materialized_view "posthog_document_embeddings_text_embedding_3_small_1536_mv" {
    to_table = "posthog.writable_posthog_document_embeddings_text_embedding_3_small_1536"
    query    = file("sql/posthog_document_embeddings_text_embedding_3_small_1536_mv.sql")

    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
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
  view "events_batch_export" {
    query = <<SQL
SELECT
  team_id AS team_id,
  timestamp AS timestamp,
  event AS event,
  distinct_id AS distinct_id,
  toString(uuid) AS uuid,
  coalesce(inserted_at, _timestamp) AS _inserted_at,
  created_at AS created_at,
  elements_chain AS elements_chain,
  toString(person_id) AS person_id,
  nullIf(properties, '') AS properties,
  nullIf(person_properties, '') AS person_properties,
  nullIf(JSONExtractString(properties, '$set'), '') AS set,
  nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
FROM posthog.events
PREWHERE
  (coalesce(events.inserted_at, events._timestamp) >= {interval_start: DateTime64}) AND (coalesce(events.inserted_at, events._timestamp) < {interval_end: DateTime64})
WHERE
  (team_id = {team_id: Int64})
AND
  (events.timestamp >= ({interval_start: DateTime64} - toIntervalDay({lookback_days: Int32})))
AND
  (events.timestamp < ({interval_end: DateTime64} + toIntervalDay(1)))
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
  view "events_batch_export_recent" {
    query = <<SQL
SELECT
  team_id AS team_id,
  timestamp AS timestamp,
  event AS event,
  distinct_id AS distinct_id,
  toString(uuid) AS uuid,
  inserted_at AS _inserted_at,
  created_at AS created_at,
  elements_chain AS elements_chain,
  toString(person_id) AS person_id,
  nullIf(properties, '') AS properties,
  nullIf(person_properties, '') AS person_properties,
  nullIf(JSONExtractString(properties, '$set'), '') AS set,
  nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
FROM posthog.events_recent
PREWHERE
  (events_recent.inserted_at >= {interval_start: DateTime64}) AND (events_recent.inserted_at < {interval_end: DateTime64})
WHERE
  (team_id = {team_id: Int64})
AND
  ((length({include_events: Array(String)}) = 0) OR (event IN ({include_events: Array(String)})))
AND
  ((length({exclude_events: Array(String)}) = 0) OR (event NOT IN ({exclude_events: Array(String)})))
ORDER BY _inserted_at ASC, event ASC
LIMIT 1 BY team_id, event, cityHash64(events_recent.distinct_id), cityHash64(events_recent.uuid)
SETTINGS
  optimize_aggregation_in_order = 1
SQL

  }
  view "events_batch_export_unbounded" {
    query = <<SQL
SELECT
  team_id AS team_id,
  timestamp AS timestamp,
  event AS event,
  distinct_id AS distinct_id,
  toString(uuid) AS uuid,
  coalesce(inserted_at, _timestamp) AS _inserted_at,
  created_at AS created_at,
  elements_chain AS elements_chain,
  toString(person_id) AS person_id,
  nullIf(properties, '') AS properties,
  nullIf(person_properties, '') AS person_properties,
  nullIf(JSONExtractString(properties, '$set'), '') AS set,
  nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
FROM posthog.events
PREWHERE
  (coalesce(events.inserted_at, events._timestamp) >= {interval_start: DateTime64}) AND (coalesce(events.inserted_at, events._timestamp) < {interval_end: DateTime64})
WHERE
  (team_id = {team_id: Int64})
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
  view "persons_batch_export" {
    query = <<SQL
WITH
  new_persons AS (SELECT id, max(version) AS version, argMax(_timestamp, person.version) AS _timestamp2 FROM posthog.person WHERE (team_id = {team_id: Int64}) AND (id IN (SELECT id FROM posthog.person WHERE (team_id = {team_id: Int64}) AND (_timestamp >= {interval_start: DateTime64}) AND (_timestamp < {interval_end: DateTime64}))) GROUP BY id HAVING ((_timestamp2 >= {interval_start: DateTime64}) AND (_timestamp2 < {interval_end: DateTime64}))),
  new_distinct_ids AS (SELECT argMax(person_id, person_distinct_id2.version) AS person_id FROM posthog.person_distinct_id2 WHERE (team_id = {team_id: Int64}) AND (distinct_id IN (SELECT distinct_id FROM posthog.person_distinct_id2 WHERE (team_id = {team_id: Int64}) AND (_timestamp >= {interval_start: DateTime64}) AND (_timestamp < {interval_end: DateTime64}))) GROUP BY distinct_id HAVING ((argMax(_timestamp, person_distinct_id2.version) >= {interval_start: DateTime64}) AND (argMax(_timestamp, person_distinct_id2.version) < {interval_end: DateTime64}))),
  all_new_persons AS (SELECT id, version FROM new_persons UNION ALL SELECT id, max(version) FROM posthog.person WHERE (team_id = {team_id: Int64}) AND (id IN (new_distinct_ids)) GROUP BY id)
SELECT
  p.team_id AS team_id,
  pd.distinct_id AS distinct_id,
  toString(p.id) AS person_id,
  p.properties AS properties,
  pd.version AS person_distinct_id_version,
  p.version AS person_version,
  p.created_at AS created_at,
  multiIf(
    ((pd._timestamp >= {interval_start: DateTime64}) AND (pd._timestamp < {interval_end: DateTime64}))
    AND (NOT ((p._timestamp >= {interval_start: DateTime64}) AND (p._timestamp < {interval_end: DateTime64}))),
    pd._timestamp,
    ((p._timestamp >= {interval_start: DateTime64}) AND (p._timestamp < {interval_end: DateTime64}))
    AND (NOT ((pd._timestamp >= {interval_start: DateTime64}) AND (pd._timestamp < {interval_end: DateTime64}))),
    p._timestamp,
    least(p._timestamp, pd._timestamp)
  ) AS _inserted_at
FROM
  posthog.person AS p INNER JOIN (SELECT distinct_id, max(version) AS version, argMax(person_id, person_distinct_id2.version) AS person_id2, argMax(_timestamp, person_distinct_id2.version) AS _timestamp FROM posthog.person_distinct_id2 WHERE (team_id = {team_id: Int64}) AND (person_id IN (SELECT id FROM all_new_persons)) GROUP BY distinct_id) AS pd ON p.id = pd.person_id2
WHERE
  (team_id = {team_id: Int64})
AND
  ((id, version) IN (all_new_persons))
ORDER BY _inserted_at ASC
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
  view "posthog_document_embeddings_union_view" {
    query = <<SQL
SELECT
  team_id,
  product,
  document_type,
  rendering,
  document_id,
  timestamp,
  inserted_at,
  content,
  metadata,
  embedding,
  _timestamp,
  _offset,
  _partition,
  'text-embedding-3-small-1536' AS model_name
FROM posthog.distributed_posthog_document_embeddings_text_embedding_3_small_1536
UNION ALL
SELECT
  team_id,
  product,
  document_type,
  rendering,
  document_id,
  timestamp,
  inserted_at,
  content,
  metadata,
  embedding,
  _timestamp,
  _offset,
  _partition,
  'text-embedding-3-large-3072' AS model_name
FROM posthog.distributed_posthog_document_embeddings_text_embedding_3_large_3072
SQL

  }
  view "raw_sessions_v" {
    query = <<SQL
SELECT
  session_id_v7,
  fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000)) AS session_timestamp,
  team_id,
  argMaxMerge(distinct_id) AS distinct_id,
  min(min_timestamp) AS min_timestamp,
  max(max_timestamp) AS max_timestamp,
  max(max_inserted_at) AS max_inserted_at,
  arrayDistinct(arrayFlatten(groupArray(urls))) AS urls,
  argMinMerge(entry_url) AS entry_url,
  argMaxMerge(end_url) AS end_url,
  argMaxMerge(last_external_click_url) AS last_external_click_url,
  argMinMerge(initial_browser) AS initial_browser,
  argMinMerge(initial_browser_version) AS initial_browser_version,
  argMinMerge(initial_os) AS initial_os,
  argMinMerge(initial_os_version) AS initial_os_version,
  argMinMerge(initial_device_type) AS initial_device_type,
  argMinMerge(initial_viewport_width) AS initial_viewport_width,
  argMinMerge(initial_viewport_height) AS initial_viewport_height,
  argMinMerge(initial_geoip_country_code) AS initial_geoip_country_code,
  argMinMerge(initial_geoip_subdivision_1_code) AS initial_geoip_subdivision_1_code,
  argMinMerge(initial_geoip_subdivision_1_name) AS initial_geoip_subdivision_1_name,
  argMinMerge(initial_geoip_subdivision_city_name) AS initial_geoip_subdivision_city_name,
  argMinMerge(initial_geoip_time_zone) AS initial_geoip_time_zone,
  argMinMerge(initial_utm_source) AS initial_utm_source,
  argMinMerge(initial_utm_campaign) AS initial_utm_campaign,
  argMinMerge(initial_utm_medium) AS initial_utm_medium,
  argMinMerge(initial_utm_term) AS initial_utm_term,
  argMinMerge(initial_utm_content) AS initial_utm_content,
  argMinMerge(initial_referring_domain) AS initial_referring_domain,
  argMinMerge(initial_gclid) AS initial_gclid,
  argMinMerge(initial_gad_source) AS initial_gad_source,
  argMinMerge(initial_gclsrc) AS initial_gclsrc,
  argMinMerge(initial_dclid) AS initial_dclid,
  argMinMerge(initial_gbraid) AS initial_gbraid,
  argMinMerge(initial_wbraid) AS initial_wbraid,
  argMinMerge(initial_fbclid) AS initial_fbclid,
  argMinMerge(initial_msclkid) AS initial_msclkid,
  argMinMerge(initial_twclid) AS initial_twclid,
  argMinMerge(initial_li_fat_id) AS initial_li_fat_id,
  argMinMerge(initial_mc_cid) AS initial_mc_cid,
  argMinMerge(initial_igshid) AS initial_igshid,
  argMinMerge(initial_ttclid) AS initial_ttclid,
  argMinMerge(initial__kx) AS initial__kx,
  argMinMerge(initial_irclid) AS initial_irclid,
  sum(pageview_count) AS pageview_count,
  uniqMerge(pageview_uniq) AS pageview_uniq,
  sum(autocapture_count) AS autocapture_count,
  uniqMerge(autocapture_uniq) AS autocapture_uniq,
  sum(screen_count) AS screen_count,
  uniqMerge(screen_uniq) AS screen_uniq,
  max(maybe_has_session_replay) AS maybe_has_session_replay,
  uniqUpToMerge(1)(page_screen_autocapture_uniq_up_to) AS page_screen_autocapture_uniq_up_to,
  argMinMerge(vitals_lcp) AS vitals_lcp
FROM posthog.raw_sessions
GROUP BY
  session_id_v7, team_id
SQL

  }
  view "raw_sessions_v3_v" {
    query = <<SQL
SELECT
  session_id_v7,
  session_timestamp,
  team_id,
  argMaxMerge(distinct_id) AS distinct_id,
  groupUniqArrayMerge(distinct_ids) AS distinct_ids,
  min(min_timestamp) AS min_timestamp,
  max(max_timestamp) AS max_timestamp,
  max(max_inserted_at) AS max_inserted_at,
  groupUniqArrayArray(2000)(urls) AS urls,
  argMinMerge(entry_url) AS entry_url,
  argMaxMerge(end_url) AS end_url,
  argMaxMerge(last_external_click_url) AS last_external_click_url,
  argMinMerge(browser) AS browser,
  argMinMerge(browser_version) AS browser_version,
  argMinMerge(os) AS os,
  argMinMerge(os_version) AS os_version,
  argMinMerge(device_type) AS device_type,
  argMinMerge(viewport_width) AS viewport_width,
  argMinMerge(viewport_height) AS viewport_height,
  argMinMerge(geoip_country_code) AS geoip_country_code,
  argMinMerge(geoip_subdivision_1_code) AS geoip_subdivision_1_code,
  argMinMerge(geoip_subdivision_1_name) AS geoip_subdivision_1_name,
  argMinMerge(geoip_subdivision_city_name) AS geoip_subdivision_city_name,
  argMinMerge(geoip_time_zone) AS geoip_time_zone,
  argMinMerge(entry_utm_source) AS entry_utm_source,
  argMinMerge(entry_utm_campaign) AS entry_utm_campaign,
  argMinMerge(entry_utm_medium) AS entry_utm_medium,
  argMinMerge(entry_utm_term) AS entry_utm_term,
  argMinMerge(entry_utm_content) AS entry_utm_content,
  argMinMerge(entry_referring_domain) AS entry_referring_domain,
  argMinMerge(entry_gclid) AS entry_gclid,
  argMinMerge(entry_gad_source) AS entry_gad_source,
  argMinMerge(entry_fbclid) AS entry_fbclid,
  argMinMerge(entry_has_gclid) AS entry_has_gclid,
  argMinMerge(entry_has_fbclid) AS entry_has_fbclid,
  argMinMerge(entry_ad_ids_map) AS entry_ad_ids_map,
  argMinMerge(entry_ad_ids_set) AS entry_ad_ids_set,
  argMinMerge(entry_channel_type_properties) AS entry_channel_type_properties,
  uniqExactMerge(pageview_uniq) AS pageview_uniq,
  uniqExactMerge(autocapture_uniq) AS autocapture_uniq,
  uniqExactMerge(screen_uniq) AS screen_uniq,
  uniqUpToMerge(1)(page_screen_uniq_up_to) AS page_screen_uniq_up_to,
  max(has_autocapture) AS has_autocapture,
  groupUniqArrayMapMerge(flag_values) AS flag_values,
  groupUniqArrayArray(flag_keys) AS flag_keys,
  groupUniqArrayArray(2000)(event_names) AS event_names,
  groupUniqArrayArray(100)(hosts) AS hosts,
  groupUniqArrayArray(10)(emails) AS emails,
  max(has_replay_events) AS has_replay_events
FROM posthog.raw_sessions_v3
GROUP BY
  session_id_v7, session_timestamp, team_id
SQL

  }
  view "sessions_v" {
    query = <<SQL
SELECT
  session_id,
  team_id,
  any(distinct_id) AS distinct_id,
  min(min_timestamp) AS min_timestamp,
  max(max_timestamp) AS max_timestamp,
  arrayDistinct(arrayFlatten(groupArray(urls))) AS urls,
  argMinMerge(entry_url) AS entry_url,
  argMaxMerge(exit_url) AS exit_url,
  argMinMerge(initial_utm_source) AS initial_utm_source,
  argMinMerge(initial_utm_campaign) AS initial_utm_campaign,
  argMinMerge(initial_utm_medium) AS initial_utm_medium,
  argMinMerge(initial_utm_term) AS initial_utm_term,
  argMinMerge(initial_utm_content) AS initial_utm_content,
  argMinMerge(initial_referring_domain) AS initial_referring_domain,
  argMinMerge(initial_gclid) AS initial_gclid,
  argMinMerge(initial_gad_source) AS initial_gad_source,
  argMinMerge(initial_gclsrc) AS initial_gclsrc,
  argMinMerge(initial_dclid) AS initial_dclid,
  argMinMerge(initial_gbraid) AS initial_gbraid,
  argMinMerge(initial_wbraid) AS initial_wbraid,
  argMinMerge(initial_fbclid) AS initial_fbclid,
  argMinMerge(initial_msclkid) AS initial_msclkid,
  argMinMerge(initial_twclid) AS initial_twclid,
  argMinMerge(initial_li_fat_id) AS initial_li_fat_id,
  argMinMerge(initial_mc_cid) AS initial_mc_cid,
  argMinMerge(initial_igshid) AS initial_igshid,
  argMinMerge(initial_ttclid) AS initial_ttclid,
  argMinMerge(initial_epik) AS initial_epik,
  argMinMerge(initial_qclid) AS initial_qclid,
  argMinMerge(initial_sccid) AS initial_sccid,
  sumMap(event_count_map) AS event_count_map,
  sum(pageview_count) AS pageview_count,
  sum(autocapture_count) AS autocapture_count
FROM posthog.sessions
GROUP BY
  session_id, team_id
SQL

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
  table "sharded_billing_usage_records" {
    order_by     = ["team_id", "toDate(timestamp)", "producer_id", "usage_key", "record_id"]
    partition_by = "toYYYYMM(timestamp)"
    settings = {
      index_granularity = "8192"
    }
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.sharded_billing_usage_records"
      replica_name   = "{replica}"
      version_column = "inserted_at"
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
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_billing_usage_records"
      sharding_key    = "cityHash64(team_id)"
    }
  }
}
