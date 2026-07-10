database "posthog" {
  table "adhoc_events_deletion" {
    order_by = ["team_id", "uuid"]
    ttl      = "deleted_at + toIntervalMonth(3)"
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

  table "ai_events" {
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "LowCardinality(String)"
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
    column "person_id" {
      type = "UUID"
    }
    column "properties" {
      type = "String"
    }
    column "retention_days" {
      type    = "Int16"
      default = "30"
    }
    column "drop_date" {
      type         = "Date"
      materialized = "toDate(timestamp) + toIntervalDay(retention_days)"
    }
    column "trace_id" {
      type = "String"
    }
    column "session_id" {
      type = "Nullable(String)"
    }
    column "parent_id" {
      type = "Nullable(String)"
    }
    column "span_id" {
      type = "Nullable(String)"
    }
    column "span_type" {
      type = "LowCardinality(Nullable(String))"
    }
    column "generation_id" {
      type = "Nullable(String)"
    }
    column "experiment_id" {
      type = "Nullable(String)"
    }
    column "span_name" {
      type = "Nullable(String)"
    }
    column "trace_name" {
      type = "Nullable(String)"
    }
    column "prompt_name" {
      type = "Nullable(String)"
    }
    column "model" {
      type = "LowCardinality(Nullable(String))"
    }
    column "provider" {
      type = "LowCardinality(Nullable(String))"
    }
    column "framework" {
      type = "LowCardinality(Nullable(String))"
    }
    column "total_tokens" {
      type = "Nullable(Int64)"
    }
    column "input_tokens" {
      type = "Nullable(Int64)"
    }
    column "output_tokens" {
      type = "Nullable(Int64)"
    }
    column "text_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "text_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "image_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "image_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "audio_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "audio_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "video_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "video_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "reasoning_tokens" {
      type = "Nullable(Int64)"
    }
    column "cache_read_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "cache_creation_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "web_search_count" {
      type = "Nullable(Int64)"
    }
    column "input_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "output_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "total_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "request_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "web_search_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "audio_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "image_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "video_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "latency" {
      type = "Nullable(Float64)"
    }
    column "time_to_first_token" {
      type = "Nullable(Float64)"
    }
    column "is_error" {
      type = "UInt8"
    }
    column "error" {
      type = "Nullable(String)"
    }
    column "error_type" {
      type = "LowCardinality(Nullable(String))"
    }
    column "error_normalized" {
      type = "Nullable(String)"
    }
    column "input" {
      type = "Nullable(String)"
    }
    column "output" {
      type = "Nullable(String)"
    }
    column "output_choices" {
      type = "Nullable(String)"
    }
    column "input_state" {
      type = "Nullable(String)"
    }
    column "output_state" {
      type = "Nullable(String)"
    }
    column "tools" {
      type = "Nullable(String)"
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
      cluster_name    = "ai_events"
      remote_database = "posthog"
      remote_table    = "sharded_ai_events"
      sharding_key    = "cityHash64(concat(toString(team_id), '-', trace_id, '-', toString(toDate(timestamp))))"
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

  table "cohortpeople" {
    order_by = ["team_id", "cohort_id", "person_id", "version"]
    settings = {
      index_granularity = "8192"
    }
    column "person_id" {
      type = "UUID"
    }
    column "cohort_id" {
      type = "Int64"
    }
    column "team_id" {
      type = "Int64"
    }
    column "sign" {
      type = "Int8"
    }
    column "version" {
      type = "UInt64"
    }
    engine "replicated_collapsing_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.cohortpeople"
      replica_name = "{replica}-{shard}"
      sign_column  = "sign"
    }
  }

  table "conversion_goal_attributed_preaggregated" {
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
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_conversion_goal_attributed_preaggregated"
      sharding_key    = "cityHash64(person_id)"
    }
  }

  table "custom_metrics_counter_events" {
    order_by     = ["name", "timestamp"]
    partition_by = "toYYYYMM(timestamp)"
    settings = {
      index_granularity = "8192"
    }
    column "name" {
      type = "String"
    }
    column "timestamp" {
      type    = "DateTime64(3, 'UTC')"
      default = "now()"
    }
    column "labels" {
      type = "Map(String, String)"
    }
    column "increment" {
      type = "Float64"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.metrics_counter_events"
      replica_name = "{replica}-{shard}"
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

  table "events" {
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
    column "$window_id" {
      type    = "String"
      comment = "column_materializer::$window_id"
    }
    column "$session_id" {
      type    = "String"
      comment = "column_materializer::$session_id"
    }
    column "$session_id_uuid" {
      type = "Nullable(UInt128)"
    }
    column "elements_chain_href" {
      type    = "String"
      comment = "column_materializer::elements_chain::href"
    }
    column "elements_chain_texts" {
      type    = "Array(String)"
      comment = "column_materializer::elements_chain::texts"
    }
    column "elements_chain_ids" {
      type    = "Array(String)"
      comment = "column_materializer::elements_chain::ids"
    }
    column "elements_chain_elements" {
      type    = "Array(Enum8('a'=1, 'button'=2, 'form'=3, 'input'=4, 'select'=5, 'textarea'=6, 'label'=7))"
      comment = "column_materializer::elements_chain::elements"
    }
    column "properties_group_custom" {
      type = "Map(String, String)"
    }
    column "properties_group_ai" {
      type = "Map(String, String)"
    }
    column "properties_group_feature_flags" {
      type = "Map(String, String)"
    }
    column "person_properties_map_custom" {
      type = "Map(String, String)"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "inserted_at" {
      type    = "Nullable(DateTime64(6, 'UTC'))"
      default = "now64()"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
    column "is_deleted" {
      type = "Bool"
    }
    column "mat_$ai_trace_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_trace_id"
    }
    column "mat_$ai_session_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_session_id"
    }
    column "mat_$ai_is_error" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_is_error"
    }
    column "mat_$ai_prompt_name" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_prompt_name"
    }
    column "mat_$ai_experiment_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_experiment_id"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_events"
      sharding_key    = "sipHash64(distinct_id)"
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

  table "events_recent" {
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

  table "experiment_metric_events_preaggregated" {
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
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_experiment_metric_events_preaggregated"
      sharding_key    = "cityHash64(entity_id)"
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
      expr        = "is_deleted"
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

  table "hog_invocation_results_data" {
    order_by     = ["team_id", "function_kind", "function_id", "invocation_id"]
    partition_by = "toYYYYMMDD(scheduled_at)"
    ttl          = "toDate(scheduled_at) + toIntervalDay(30)"
    settings = {
      index_granularity   = "1024"
      ttl_only_drop_parts = "1"
    }
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
      type    = "DateTime64(6, 'UTC')"
      default = "scheduled_at"
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
      type    = "UInt8"
      default = "0"
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
    index "status_idx" {
      expr        = "status"
      type        = "set(8)"
      granularity = 1
    }
    index "function_idx" {
      expr        = "function_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "event_uuid_idx" {
      expr        = "event_uuid"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "is_retry_idx" {
      expr        = "is_retry"
      type        = "set(2)"
      granularity = 1
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.hog_invocation_results_data"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
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

  table "ingestion_warnings_v2" {
    order_by     = ["team_id", "type", "timestamp"]
    partition_by = "toYYYYMM(timestamp)"
    ttl          = "toDateTime(timestamp) + toIntervalDay(90)"
    settings = {
      index_granularity = "8192"
    }
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
      type    = "LowCardinality(String)"
      default = "coalesce(nullIf(JSONExtractString(details, 'category'), ''), 'unknown')"
    }
    column "severity" {
      type    = "LowCardinality(String)"
      default = "coalesce(nullIf(JSONExtractString(details, 'severity'), ''), 'warning')"
    }
    column "pipeline_step" {
      type    = "LowCardinality(String)"
      default = "coalesce(nullIf(JSONExtractString(details, 'pipelineStep'), ''), 'unknown')"
    }
    column "event_uuid" {
      type    = "Nullable(UUID)"
      default = "toUUIDOrNull(JSONExtractString(details, 'eventUuid'))"
    }
    column "distinct_id" {
      type    = "Nullable(String)"
      default = "nullIf(JSONExtractString(details, 'distinctId'), '')"
    }
    column "group_key" {
      type    = "Nullable(String)"
      default = "nullIf(JSONExtractString(details, 'groupKey'), '')"
    }
    column "person_id" {
      type    = "Nullable(UUID)"
      default = "toUUIDOrNull(JSONExtractString(details, 'personId'))"
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
      zoo_path     = "/clickhouse/tables/noshard/posthog.ingestion_warnings_v2"
      replica_name = "{replica}-{shard}"
    }
  }

  table "ingestion_warnings_v2_distributed" {
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
      type    = "LowCardinality(String)"
      default = "coalesce(nullIf(JSONExtractString(details, 'category'), ''), 'unknown')"
    }
    column "severity" {
      type    = "LowCardinality(String)"
      default = "coalesce(nullIf(JSONExtractString(details, 'severity'), ''), 'warning')"
    }
    column "pipeline_step" {
      type    = "LowCardinality(String)"
      default = "coalesce(nullIf(JSONExtractString(details, 'pipelineStep'), ''), 'unknown')"
    }
    column "event_uuid" {
      type    = "Nullable(UUID)"
      default = "toUUIDOrNull(JSONExtractString(details, 'eventUuid'))"
    }
    column "distinct_id" {
      type    = "Nullable(String)"
      default = "nullIf(JSONExtractString(details, 'distinctId'), '')"
    }
    column "group_key" {
      type    = "Nullable(String)"
      default = "nullIf(JSONExtractString(details, 'groupKey'), '')"
    }
    column "person_id" {
      type    = "Nullable(UUID)"
      default = "toUUIDOrNull(JSONExtractString(details, 'personId'))"
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
      remote_table    = "ingestion_warnings_v2"
    }
  }

  table "kafka_ai_events_json" {
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
    column "person_properties" {
      type = "String"
    }
    column "person_created_at" {
      type = "DateTime64(3)"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_ai_events_json'"
      group_name  = "kafka_group_name = 'group1'"
      format      = "kafka_format = 'JSONEachRow'"
    }
  }

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

  table "kafka_error_tracking_fingerprint_issue_state" {
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
    engine "kafka" {
      broker_list = "msk_cluster"
      topic_list  = "kafka_topic_list = 'clickhouse_error_tracking_fingerprint_issue_state'"
      group_name  = "kafka_group_name = 'clickhouse-error-tracking-fingerprint-issue-state'"
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

  table "kafka_hog_invocation_results" {
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
    engine "kafka" {
      broker_list          = "warpstream_cyclotron"
      topic_list           = "kafka_topic_list = 'clickhouse_hog_invocation_results'"
      group_name           = "kafka_group_name = 'clickhouse_hog_invocation_results'"
      format               = "kafka_format = 'JSONEachRow'"
      skip_broken_messages = 100
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

  table "kafka_ingestion_warnings_v2" {
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
    engine "kafka" {
      broker_list = "warpstream_ingestion"
      topic_list  = "kafka_topic_list = 'clickhouse_ingestion_warnings'"
      group_name  = "kafka_group_name = 'clickhouse_ingestion_warnings_v2'"
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

  table "kafka_logs_avro" {
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

  table "kafka_message_assets" {
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
    engine "kafka" {
      broker_list          = "warpstream_cyclotron"
      topic_list           = "kafka_topic_list = 'clickhouse_message_assets'"
      group_name           = "kafka_group_name = 'clickhouse_message_assets'"
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

  table "kafka_property_values" {
    column "team_id" {
      type = "Int64"
    }
    column "property_type" {
      type = "LowCardinality(String)"
    }
    column "property_key" {
      type = "String"
    }
    column "property_value" {
      type = "String"
    }
    column "property_count" {
      type = "UInt64"
    }
    engine "kafka" {
      broker_list         = "warpstream_ingestion"
      topic_list          = "kafka_topic_list = 'clickhouse_property_values'"
      group_name          = "kafka_group_name = 'clickhouse_property_values'"
      format              = "kafka_format = 'JSONEachRow'"
      num_consumers       = 8
      thread_per_consumer = true
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

  table "log_attributes" {
    order_by     = ["team_id", "attribute_type", "time_bucket", "resource_fingerprint", "attribute_key", "attribute_value"]
    partition_by = "toDate(original_expiry_time_bucket)"
    settings = {
      deduplicate_merge_projection_mode = "drop"
      index_granularity                 = "8192"
      storage_policy                    = "default"
    }
    column "team_id" {
      type  = "Int32"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "time_bucket" {
      type  = "DateTime64(0)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "original_expiry_time_bucket" {
      type  = "DateTime64(0)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "service_name" {
      type  = "LowCardinality(String)"
      codec = "ZSTD(1)"
    }
    column "resource_fingerprint" {
      type    = "UInt64"
      default = "0"
      codec   = "DoubleDelta, ZSTD(1)"
    }
    column "attribute_key" {
      type  = "LowCardinality(String)"
      codec = "ZSTD(1)"
    }
    column "attribute_value" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "attribute_type" {
      type = "LowCardinality(String)"
    }
    index "idx_attribute_key" {
      expr        = "attribute_key"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attribute_value" {
      expr        = "attribute_value"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attribute_key_n3" {
      expr        = "attribute_key"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 1
    }
    index "idx_attribute_value_n3" {
      expr        = "attribute_value"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 1
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.log_attributes"
      replica_name = "{replica}-{shard}"
    }
  }

  table "log_attributes2" {
    order_by     = ["team_id", "attribute_type", "time_bucket", "resource_fingerprint", "attribute_key", "attribute_value"]
    partition_by = "toDate(original_expiry_time_bucket)"
    ttl          = "original_expiry_time_bucket"
    settings = {
      deduplicate_merge_projection_mode = "drop"
      index_granularity                 = "8192"
    }
    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_fingerprint" {
      type    = "UInt64"
      default = "0"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type  = "String"
      codec = "ZSTD(5)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "attribute_type" {
      type    = "LowCardinality(String)"
      default = "'log'"
    }
    column "original_expiry_time_bucket" {
      type    = "DateTime"
      default = "now()"
    }
    index "idx_attribute_key" {
      expr        = "attribute_key"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attribute_value" {
      expr        = "attribute_value"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attribute_key_n3" {
      expr        = "attribute_key"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 1
    }
    index "idx_attribute_value_n3" {
      expr        = "attribute_value"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 1
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.log_attributes2"
      replica_name = "{replica}-{shard}"
    }
  }

  table "log_attributes3" {
    order_by     = ["team_id", "attribute_type", "time_bucket", "resource_fingerprint", "attribute_key", "attribute_value", "severity_text"]
    partition_by = "toDate(original_expiry_time_bucket)"
    ttl          = "original_expiry_time_bucket"
    settings = {
      deduplicate_merge_projection_mode = "drop"
      index_granularity                 = "8192"
    }
    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_fingerprint" {
      type    = "UInt64"
      default = "0"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type  = "String"
      codec = "ZSTD(5)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "attribute_type" {
      type    = "LowCardinality(String)"
      default = "'log'"
    }
    column "original_expiry_time_bucket" {
      type    = "DateTime"
      default = "now()"
    }
    column "severity_text" {
      type = "LowCardinality(String)"
    }
    index "idx_attribute_key" {
      expr        = "attribute_key"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attribute_value" {
      expr        = "attribute_value"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attribute_key_n3" {
      expr        = "attribute_key"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 1
    }
    index "idx_attribute_value_n3" {
      expr        = "attribute_value"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 1
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.log_attributes3"
      replica_name = "{replica}-{shard}"
    }
  }

  table "log_attributes_distributed" {
    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_fingerprint" {
      type    = "UInt64"
      default = "0"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type  = "String"
      codec = "ZSTD(5)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "attribute_type" {
      type    = "LowCardinality(String)"
      default = "'log'"
    }
    column "original_expiry_time_bucket" {
      type    = "DateTime"
      default = "now()"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "log_attributes2"
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

  table "logs" {
    column "time_bucket" {
      type         = "DateTime"
      materialized = "toStartOfDay(timestamp)"
      codec        = "DoubleDelta, ZSTD(1)"
    }
    column "original_expiry_timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "uuid" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "team_id" {
      type  = "Int32"
      codec = "ZSTD(1)"
    }
    column "trace_id" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "span_id" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "trace_flags" {
      type  = "Int32"
      codec = "ZSTD(1)"
    }
    column "timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "observed_timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "created_at" {
      type         = "DateTime64(6)"
      materialized = "now()"
      codec        = "DoubleDelta, ZSTD(1)"
    }
    column "body" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "severity_text" {
      type  = "LowCardinality(String)"
      codec = "ZSTD(1)"
    }
    column "severity_number" {
      type  = "Int32"
      codec = "ZSTD(1)"
    }
    column "service_name" {
      type  = "LowCardinality(String)"
      codec = "ZSTD(1)"
    }
    column "resource_attributes" {
      type  = "Map(LowCardinality(String), String)"
      codec = "ZSTD(1)"
    }
    column "resource_fingerprint" {
      type         = "UInt64"
      materialized = "cityHash64(resource_attributes)"
      codec        = "DoubleDelta, ZSTD(1)"
    }
    column "instrumentation_scope" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "event_name" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "attributes_map_str" {
      type  = "Map(LowCardinality(String), String)"
      codec = "ZSTD(1)"
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
      codec        = "ZSTD(1)"
    }
    column "attributes_map_datetime" {
      type         = "Map(LowCardinality(String), DateTime64(6))"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str))"
      codec        = "ZSTD(1)"
    }
    column "_partition" {
      type  = "UInt32"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_topic" {
      type = "String"
    }
    column "_offset" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_bytes_uncompressed" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_bytes_compressed" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_record_count" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "logs32"
    }
  }

  table "logs32" {
    order_by     = ["team_id", "time_bucket", "service_name", "resource_fingerprint", "severity_text", "timestamp"]
    partition_by = "toDate(original_expiry_timestamp)"
    settings = {
      add_minmax_index_for_numeric_columns  = "1"
      allow_experimental_reverse_key        = "1"
      allow_remote_fs_zero_copy_replication = "1"
      index_granularity                     = "8192"
      index_granularity_bytes               = "104857600"
      storage_policy                        = "default"
      ttl_only_drop_parts                   = "1"
    }
    column "time_bucket" {
      type         = "DateTime"
      materialized = "toStartOfDay(timestamp)"
      codec        = "DoubleDelta, ZSTD(1)"
    }
    column "original_expiry_timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "uuid" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "team_id" {
      type  = "Int32"
      codec = "ZSTD(1)"
    }
    column "trace_id" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "span_id" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "trace_flags" {
      type  = "Int32"
      codec = "ZSTD(1)"
    }
    column "timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "observed_timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "created_at" {
      type         = "DateTime64(6)"
      materialized = "now()"
      codec        = "DoubleDelta, ZSTD(1)"
    }
    column "body" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "severity_text" {
      type  = "LowCardinality(String)"
      codec = "ZSTD(1)"
    }
    column "severity_number" {
      type  = "Int32"
      codec = "ZSTD(1)"
    }
    column "service_name" {
      type  = "LowCardinality(String)"
      codec = "ZSTD(1)"
    }
    column "resource_attributes" {
      type  = "Map(LowCardinality(String), String)"
      codec = "ZSTD(1)"
    }
    column "resource_fingerprint" {
      type         = "UInt64"
      materialized = "cityHash64(resource_attributes)"
      codec        = "DoubleDelta, ZSTD(1)"
    }
    column "instrumentation_scope" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "event_name" {
      type  = "String"
      codec = "ZSTD(1)"
    }
    column "attributes_map_str" {
      type  = "Map(LowCardinality(String), String)"
      codec = "ZSTD(1)"
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
      codec        = "ZSTD(1)"
    }
    column "attributes_map_datetime" {
      type         = "Map(LowCardinality(String), DateTime64(6))"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str))"
      codec        = "ZSTD(1)"
    }
    column "_partition" {
      type  = "UInt32"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_topic" {
      type = "String"
    }
    column "_offset" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_bytes_uncompressed" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_bytes_compressed" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "_record_count" {
      type  = "UInt64"
      codec = "DoubleDelta, ZSTD(1)"
    }
    index "idx_severity_text_set" {
      expr        = "severity_text"
      type        = "set(10)"
      granularity = 1
    }
    index "idx_attributes_str_keys" {
      expr        = "mapKeys(attributes_map_str)"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attributes_str_values" {
      expr        = "mapValues(attributes_map_str)"
      type        = "bloom_filter(0.001)"
      granularity = 1
    }
    index "idx_mat_body_ipv4_matches" {
      expr        = "mat_body_ipv4_matches"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_body_ngram3" {
      expr        = "lower(body)"
      type        = "ngrambf_v1(3, 25000, 2, 0)"
      granularity = 1
    }
    index "idx_uuid_bloom" {
      expr        = "uuid"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_observed_minmax" {
      expr        = "observed_timestamp"
      type        = "minmax"
      granularity = 1
    }
    index "idx_timestamp_minmax" {
      expr        = "timestamp"
      type        = "minmax"
      granularity = 1
    }
    projection "projection_aggregate_counts" {
      query = <<SQL
SELECT
  team_id,
  time_bucket,
  toStartOfMinute(timestamp),
  service_name,
  severity_text,
  resource_fingerprint,
  count() AS event_count
GROUP BY
  team_id, time_bucket, toStartOfMinute(timestamp), service_name, severity_text, resource_fingerprint
SQL

    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.logs32"
      replica_name = "{replica}-{shard}"
    }
  }

  table "logs34" {
    order_by     = ["team_id", "time_bucket", "service_name", "resource_fingerprint", "severity_text", "timestamp"]
    partition_by = "toDate(original_expiry_timestamp)"
    ttl          = "original_expiry_timestamp"
    settings = {
      add_minmax_index_for_numeric_columns = "1"
      allow_experimental_reverse_key       = "1"
      index_granularity                    = "8192"
      index_granularity_bytes              = "104857600"
      map_serialization_version            = "with_buckets"
      ttl_only_drop_parts                  = "1"
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
    index "idx_severity_text_set" {
      expr        = "severity_text"
      type        = "set(10)"
      granularity = 1
    }
    index "idx_attributes_str_keys" {
      expr        = "mapKeys(attributes_map_str)"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attributes_str_values" {
      expr        = "mapValues(attributes_map_str)"
      type        = "bloom_filter(0.001)"
      granularity = 1
    }
    index "idx_mat_body_ipv4_matches" {
      expr        = "mat_body_ipv4_matches"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_body_ngram3" {
      expr        = "lower(body)"
      type        = "ngrambf_v1(3, 25000, 2, 0)"
      granularity = 1
    }
    index "idx_uuid_bloom" {
      expr        = "uuid"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_observed_minmax" {
      expr        = "observed_timestamp"
      type        = "minmax"
      granularity = 1
    }
    index "idx_timestamp_minmax" {
      expr        = "timestamp"
      type        = "minmax"
      granularity = 1
    }
    projection "projection_aggregate_counts" {
      query = <<SQL
SELECT
  team_id,
  time_bucket,
  toStartOfMinute(timestamp),
  service_name,
  severity_text,
  resource_fingerprint,
  count() AS event_count
GROUP BY
  team_id, time_bucket, toStartOfMinute(timestamp), service_name, severity_text, resource_fingerprint
SQL

    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.logs34"
      replica_name = "{replica}-{shard}"
    }
  }

  table "logs_billing_metrics" {
    order_by     = ["team_id", "time_bucket", "service_name"]
    partition_by = "toYYYYMM(time_bucket)"
    settings = {
      deduplicate_merge_projection_mode = "rebuild"
      index_granularity                 = "8192"
    }
    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "bytes_uncompressed" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "bytes_compressed" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "record_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.logs_billing_metrics"
      replica_name = "{replica}-{shard}"
    }
  }

  table "logs_billing_metrics_distributed" {
    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "bytes_uncompressed" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "bytes_compressed" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "record_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "logs_billing_metrics"
    }
  }

  table "logs_distributed" {
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
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "logs34"
    }
  }

  table "logs_kafka_metrics" {
    order_by = ["_topic", "_partition"]
    settings = {
      index_granularity = "8192"
    }
    column "_partition" {
      type = "UInt32"
    }
    column "_topic" {
      type = "String"
    }
    column "max_offset" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "max_observed_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_created_at" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_lag" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.logs_kafka_metrics"
      replica_name = "{replica}-{shard}"
    }
  }

  table "logs_kafka_metrics_distributed" {
    column "_partition" {
      type = "UInt32"
    }
    column "_topic" {
      type = "String"
    }
    column "max_offset" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "max_observed_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_created_at" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_lag" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "logs_kafka_metrics"
    }
  }

  table "marketing_conversions_preaggregated" {
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
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_marketing_conversions_preaggregated"
      sharding_key    = "cityHash64(person_id)"
    }
  }

  table "marketing_costs_preaggregated" {
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
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_marketing_costs_preaggregated"
      sharding_key    = "cityHash64(source_name, campaign_id)"
    }
  }

  table "marketing_touchpoints_preaggregated" {
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

  table "message_assets_data" {
    order_by     = ["team_id", "function_kind", "function_id", "invocation_id", "action_id"]
    partition_by = "toYYYYMMDD(sent_at)"
    ttl          = "toDate(sent_at) + toIntervalDay(30)"
    settings = {
      index_granularity   = "1024"
      ttl_only_drop_parts = "1"
    }
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
      type    = "UInt8"
      default = "0"
    }
    column "html" {
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
    index "parent_run_idx" {
      expr        = "parent_run_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
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
    index "recipient_idx" {
      expr        = "recipient"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.message_assets_data"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  table "metric_samples" {
    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "series_fingerprint" {
      type  = "UInt64"
      codec = "DoubleDelta"
    }
    column "timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta"
    }
    column "value" {
      type  = "Float64"
      codec = "Gorilla(8)"
    }
    column "count" {
      type    = "UInt64"
      default = "1"
    }
    column "histogram_bounds" {
      type = "Array(Float64)"
    }
    column "histogram_counts" {
      type = "Array(UInt64)"
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
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "metric_samples1"
    }
  }

  table "metric_samples1" {
    order_by     = ["team_id", "metric_name", "series_fingerprint", "timestamp"]
    partition_by = "toDate(timestamp)"
    ttl          = "toDateTime(timestamp) + toIntervalDay(30)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "series_fingerprint" {
      type  = "UInt64"
      codec = "DoubleDelta"
    }
    column "timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta"
    }
    column "value" {
      type  = "Float64"
      codec = "Gorilla(8)"
    }
    column "count" {
      type    = "UInt64"
      default = "1"
    }
    column "histogram_bounds" {
      type = "Array(Float64)"
    }
    column "histogram_counts" {
      type = "Array(UInt64)"
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
    index "idx_trace_id_bf" {
      expr        = "trace_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.metric_samples1"
      replica_name = "{replica}-{shard}"
    }
  }

  table "metric_series" {
    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "series_fingerprint" {
      type  = "UInt64"
      codec = "DoubleDelta"
    }
    column "metric_type" {
      type = "LowCardinality(String)"
    }
    column "unit" {
      type = "LowCardinality(String)"
    }
    column "aggregation_temporality" {
      type = "LowCardinality(String)"
    }
    column "is_monotonic" {
      type    = "Bool"
      default = "false"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "last_seen" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "metric_series1"
    }
  }

  table "metric_series1" {
    order_by = ["team_id", "metric_name", "series_fingerprint"]
    ttl      = "toDateTime(last_seen) + toIntervalDay(90)"
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "series_fingerprint" {
      type  = "UInt64"
      codec = "DoubleDelta"
    }
    column "metric_type" {
      type = "LowCardinality(String)"
    }
    column "unit" {
      type = "LowCardinality(String)"
    }
    column "aggregation_temporality" {
      type = "LowCardinality(String)"
    }
    column "is_monotonic" {
      type    = "Bool"
      default = "false"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "last_seen" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta"
    }
    index "idx_service_set" {
      expr        = "service_name"
      type        = "set(1000)"
      granularity = 1
    }
    index "idx_attr_keys" {
      expr        = "mapKeys(attributes)"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attr_values" {
      expr        = "mapValues(attributes)"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.metric_series1"
      replica_name   = "{replica}-{shard}"
      version_column = "last_seen"
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

  table "person" {
    order_by = ["team_id", "id"]
    settings = {
      index_granularity = "8192"
    }
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
    index "kafka_timestamp_minmax_person" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.person"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
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

  table "person_distinct_id2" {
    order_by = ["team_id", "distinct_id"]
    settings = {
      index_granularity = "512"
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
    index "kafka_timestamp_minmax_person_distinct_id2" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.person_distinct_id2"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  table "person_distinct_id_overrides" {
    order_by = ["team_id", "distinct_id"]
    settings = {
      index_granularity = "512"
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
    index "kafka_timestamp_minmax_person_distinct_id_overrides" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.person_distinct_id_overrides"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
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

  table "person_static_cohort" {
    order_by = ["team_id", "cohort_id", "person_id", "id"]
    settings = {
      index_granularity = "8192"
    }
    column "id" {
      type = "UUID"
    }
    column "person_id" {
      type = "UUID"
    }
    column "cohort_id" {
      type = "Int64"
    }
    column "team_id" {
      type = "Int64"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.person_static_cohort"
      replica_name   = "{replica}-{shard}"
      version_column = "_timestamp"
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
      materialized = "bitShiftLeft(toUInt64(NOT isNull(property_type)), 48) + toUInt64(toUnixTimestamp(last_seen_at))"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.property_definitions"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  table "property_values" {
    order_by = ["team_id", "property_type", "property_key", "property_value"]
    ttl      = "last_seen + toIntervalDay(30)"
    settings = {
      index_granularity = "8192"
    }
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
    index "idx_property_value_ngrambf" {
      expr        = "lower(property_value)"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 1
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.property_values"
      replica_name = "{replica}-{shard}"
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

  table "query_log_archive_buffer" {
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
    engine "buffer" {
      database   = "posthog"
      table      = "sharded_query_log_archive"
      num_layers = 16
      min_time   = 10
      max_time   = 60
      min_rows   = 10000
      max_rows   = 1000000
      min_bytes  = 10000000
      max_bytes  = 100000000
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

  table "raw_error_tracking_fingerprint_issue_state" {
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
    column "issue_name" {
      type = "Nullable(String)"
    }
    column "issue_description" {
      type = "Nullable(String)"
    }
    column "issue_status" {
      type = "String"
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
    index "kafka_timestamp_minmax_raw_error_tracking_fingerprint_issue_state" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.raw_error_tracking_fingerprint_issue_state"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  table "raw_sessions" {
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

  table "session_replay_features" {
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

  table "sessions" {
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

  table "sharded_ai_events" {
    order_by     = ["team_id", "trace_id", "timestamp"]
    partition_by = "toYYYYMM(drop_date)"
    ttl          = "drop_date"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "LowCardinality(String)"
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
    column "person_id" {
      type = "UUID"
    }
    column "properties" {
      type = "String"
    }
    column "retention_days" {
      type    = "Int16"
      default = "30"
    }
    column "drop_date" {
      type         = "Date"
      materialized = "toDate(timestamp) + toIntervalDay(retention_days)"
    }
    column "trace_id" {
      type = "String"
    }
    column "session_id" {
      type = "Nullable(String)"
    }
    column "parent_id" {
      type = "Nullable(String)"
    }
    column "span_id" {
      type = "Nullable(String)"
    }
    column "span_type" {
      type = "LowCardinality(Nullable(String))"
    }
    column "generation_id" {
      type = "Nullable(String)"
    }
    column "experiment_id" {
      type = "Nullable(String)"
    }
    column "span_name" {
      type = "Nullable(String)"
    }
    column "trace_name" {
      type = "Nullable(String)"
    }
    column "prompt_name" {
      type = "Nullable(String)"
    }
    column "model" {
      type = "LowCardinality(Nullable(String))"
    }
    column "provider" {
      type = "LowCardinality(Nullable(String))"
    }
    column "framework" {
      type = "LowCardinality(Nullable(String))"
    }
    column "total_tokens" {
      type = "Nullable(Int64)"
    }
    column "input_tokens" {
      type = "Nullable(Int64)"
    }
    column "output_tokens" {
      type = "Nullable(Int64)"
    }
    column "text_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "text_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "image_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "image_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "audio_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "audio_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "video_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "video_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "reasoning_tokens" {
      type = "Nullable(Int64)"
    }
    column "cache_read_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "cache_creation_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "web_search_count" {
      type = "Nullable(Int64)"
    }
    column "input_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "output_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "total_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "request_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "web_search_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "audio_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "image_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "video_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "latency" {
      type = "Nullable(Float64)"
    }
    column "time_to_first_token" {
      type = "Nullable(Float64)"
    }
    column "is_error" {
      type = "UInt8"
    }
    column "error" {
      type = "Nullable(String)"
    }
    column "error_type" {
      type = "LowCardinality(Nullable(String))"
    }
    column "error_normalized" {
      type = "Nullable(String)"
    }
    column "input" {
      type = "Nullable(String)"
    }
    column "output" {
      type = "Nullable(String)"
    }
    column "output_choices" {
      type = "Nullable(String)"
    }
    column "input_state" {
      type = "Nullable(String)"
    }
    column "output_state" {
      type = "Nullable(String)"
    }
    column "tools" {
      type = "Nullable(String)"
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
    index "idx_trace_id" {
      expr        = "trace_id"
      type        = "bloom_filter(0.001)"
      granularity = 1
    }
    index "idx_session_id" {
      expr        = "session_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_parent_id" {
      expr        = "parent_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_span_id" {
      expr        = "span_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_prompt_name" {
      expr        = "prompt_name"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_model" {
      expr        = "model"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_experiment_id" {
      expr        = "experiment_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_event" {
      expr        = "event"
      type        = "set(20)"
      granularity = 1
    }
    index "idx_is_error" {
      expr        = "is_error"
      type        = "set(2)"
      granularity = 1
    }
    index "idx_provider" {
      expr        = "provider"
      type        = "set(50)"
      granularity = 1
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.ai_events"
      replica_name = "{replica}"
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

  table "sharded_conversion_goal_attributed_preaggregated" {
    order_by     = ["team_id", "job_id", "person_id", "conversion_timestamp", "touchpoint_timestamp"]
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.conversion_goal_attributed_preaggregated"
      replica_name   = "{replica}-{shard}"
      version_column = "computed_at"
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

  table "sharded_events" {
    order_by     = ["team_id", "toDate(timestamp)", "event", "cityHash64(distinct_id)", "cityHash64(uuid)"]
    partition_by = "toYYYYMM(timestamp)"
    sample_by    = "cityHash64(distinct_id)"
    settings = {
      index_granularity = "8192"
    }
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
    column "$group_0" {
      type         = "String"
      materialized = "replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), '^\"|\"$', '')"
      comment      = "column_materializer::$group_0"
    }
    column "$group_1" {
      type         = "String"
      materialized = "replaceRegexpAll(JSONExtractRaw(properties, '$group_1'), '^\"|\"$', '')"
      comment      = "column_materializer::$group_1"
    }
    column "$group_2" {
      type         = "String"
      materialized = "replaceRegexpAll(JSONExtractRaw(properties, '$group_2'), '^\"|\"$', '')"
      comment      = "column_materializer::$group_2"
    }
    column "$group_3" {
      type         = "String"
      materialized = "replaceRegexpAll(JSONExtractRaw(properties, '$group_3'), '^\"|\"$', '')"
      comment      = "column_materializer::$group_3"
    }
    column "$group_4" {
      type         = "String"
      materialized = "replaceRegexpAll(JSONExtractRaw(properties, '$group_4'), '^\"|\"$', '')"
      comment      = "column_materializer::$group_4"
    }
    column "$window_id" {
      type         = "String"
      materialized = "replaceRegexpAll(JSONExtractRaw(properties, '$window_id'), '^\"|\"$', '')"
      comment      = "column_materializer::$window_id"
    }
    column "$session_id" {
      type         = "String"
      materialized = "replaceRegexpAll(JSONExtractRaw(properties, '$session_id'), '^\"|\"$', '')"
      comment      = "column_materializer::$session_id"
    }
    column "$session_id_uuid" {
      type         = "Nullable(UInt128)"
      materialized = "toUInt128(JSONExtract(properties, '$session_id', 'Nullable(UUID)'))"
    }
    column "elements_chain_href" {
      type         = "String"
      materialized = "EXTRACT(elements_chain, '(?::|\")href=\"(.*?)\"')"
    }
    column "elements_chain_texts" {
      type         = "Array(String)"
      materialized = "arrayDistinct(extractAll(elements_chain, '(?::|\")text=\"(.*?)\"'))"
    }
    column "elements_chain_elements" {
      type         = "Array(Enum8('a'=1, 'button'=2, 'form'=3, 'input'=4, 'select'=5, 'textarea'=6, 'label'=7))"
      materialized = "arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\\\.|$|:)'))"
    }
    column "properties_group_custom" {
      type         = "Map(String, String)"
      materialized = "mapSort(mapFilter((key, _) -> ((key NOT LIKE '$%') AND (key NOT IN ('token', 'distinct_id', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'gad_source', 'gclsrc', 'dclid', 'gbraid', 'wbraid', 'fbclid', 'msclkid', 'twclid', 'li_fat_id', 'mc_cid', 'igshid', 'ttclid', 'rdt_cid', 'epik', 'qclid', 'sccid', 'irclid', '_kx'))), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))"
      codec        = "ZSTD(1)"
    }
    column "properties_group_ai" {
      type         = "Map(String, String)"
      materialized = "mapSort(mapFilter((key, _) -> ((key LIKE '$ai_%') AND (key NOT IN ('$ai_input', '$ai_input_state', '$ai_output', '$ai_output_choices', '$ai_output_state', '$ai_tools'))), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))"
      codec        = "ZSTD(1)"
    }
    column "properties_group_feature_flags" {
      type         = "Map(String, String)"
      materialized = "mapSort(mapFilter((key, _) -> (key LIKE '$feature/%'), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))"
      codec        = "ZSTD(1)"
    }
    column "person_properties_map_custom" {
      type         = "Map(String, String)"
      materialized = "mapSort(mapFilter((key, _) -> (key NOT LIKE '$%'), CAST(JSONExtractKeysAndValues(person_properties, 'String'), 'Map(String, String)')))"
      codec        = "ZSTD(1)"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "inserted_at" {
      type    = "Nullable(DateTime64(6, 'UTC'))"
      default = "now64()"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
    column "elements_chain_ids" {
      type         = "Array(String)"
      materialized = "arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id=\"(.*?)\"'))"
    }
    column "is_deleted" {
      type = "Bool"
    }
    column "properties_map_ephemeral" {
      type = "Map(String, String)"
    }
    column "person_properties_map_ephemeral" {
      type = "Map(String, String)"
    }
    column "mat_$ai_trace_id" {
      type         = "Nullable(String)"
      materialized = "JSONExtract(properties, '$ai_trace_id', 'Nullable(String)')"
    }
    column "mat_$ai_session_id" {
      type         = "Nullable(String)"
      materialized = "JSONExtract(properties, '$ai_session_id', 'Nullable(String)')"
    }
    column "mat_$ai_is_error" {
      type         = "Nullable(String)"
      materialized = "JSONExtract(properties, '$ai_is_error', 'Nullable(String)')"
    }
    column "mat_$ai_prompt_name" {
      type         = "Nullable(String)"
      materialized = "JSONExtract(properties, '$ai_prompt_name', 'Nullable(String)')"
    }
    column "mat_$ai_experiment_id" {
      type    = "Nullable(String)"
      default = "JSONExtract(properties, '$ai_experiment_id', 'Nullable(String)')"
    }
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
    index "minmax_$session_id_uuid" {
      expr        = "`$session_id_uuid`"
      type        = "minmax"
      granularity = 1
    }
    index "properties_group_custom_keys_bf" {
      expr        = "mapKeys(properties_group_custom)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "properties_group_custom_values_bf" {
      expr        = "mapValues(properties_group_custom)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "properties_group_ai_keys_bf" {
      expr        = "mapKeys(properties_group_ai)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "properties_group_ai_values_bf" {
      expr        = "mapValues(properties_group_ai)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "properties_group_feature_flags_keys_bf" {
      expr        = "mapKeys(properties_group_feature_flags)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "properties_group_feature_flags_values_bf" {
      expr        = "mapValues(properties_group_feature_flags)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "person_properties_map_custom_keys_bf" {
      expr        = "mapKeys(person_properties_map_custom)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "person_properties_map_custom_values_bf" {
      expr        = "mapValues(person_properties_map_custom)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "kafka_timestamp_minmax_sharded_events" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    index "minmax_inserted_at" {
      expr        = "coalesce(inserted_at, _timestamp)"
      type        = "minmax"
      granularity = 1
    }
    index "is_deleted_idx" {
      expr        = "is_deleted"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_filter_$ai_trace_id" {
      expr        = "`mat_$ai_trace_id`"
      type        = "bloom_filter(0.001)"
      granularity = 2
    }
    index "bloom_filter_$ai_session_id" {
      expr        = "`mat_$ai_session_id`"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_$ai_session_id" {
      expr        = "`mat_$ai_session_id`"
      type        = "minmax"
      granularity = 1
    }
    index "set_$ai_is_error" {
      expr        = "`mat_$ai_is_error`"
      type        = "set(7)"
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
    index "bloom_filter_$ai_prompt_name" {
      expr        = "`mat_$ai_prompt_name`"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_$ai_prompt_name" {
      expr        = "`mat_$ai_prompt_name`"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_filter_$ai_experiment_id" {
      expr        = "`mat_$ai_experiment_id`"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_$ai_experiment_id" {
      expr        = "`mat_$ai_experiment_id`"
      type        = "minmax"
      granularity = 1
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.events"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }

  table "sharded_events_recent" {
    order_by     = ["team_id", "toStartOfHour(inserted_at)", "event", "cityHash64(distinct_id)", "cityHash64(uuid)"]
    partition_by = "toStartOfDay(inserted_at)"
    ttl          = "toDateTime(inserted_at) + toIntervalDay(7)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.sharded_events_recent"
      replica_name   = "{replica}"
      version_column = "_timestamp"
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

  table "sharded_experiment_metric_events_preaggregated" {
    order_by     = ["team_id", "job_id", "entity_id", "timestamp", "event_uuid"]
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.experiment_metric_events_preaggregated"
      replica_name   = "{replica}-{shard}"
      version_column = "computed_at"
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

  table "sharded_ingestion_warnings" {
    order_by     = ["team_id", "toHour(timestamp)", "type", "source", "timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    settings = {
      index_granularity = "8192"
    }
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
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.sharded_ingestion_warnings"
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

  table "sharded_marketing_conversions_preaggregated" {
    order_by     = ["team_id", "job_id", "person_id", "conversion_timestamp"]
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.marketing_conversions_preaggregated"
      replica_name   = "{replica}-{shard}"
      version_column = "computed_at"
    }
  }

  table "sharded_marketing_costs_preaggregated" {
    order_by     = ["team_id", "job_id", "source_name", "grain", "campaign_id", "ad_group_id", "ad_id", "cost_date"]
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.marketing_costs_preaggregated"
      replica_name   = "{replica}-{shard}"
      version_column = "computed_at"
    }
  }

  table "sharded_marketing_touchpoints_preaggregated" {
    order_by     = ["team_id", "job_id", "person_id", "touchpoint_timestamp"]
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.marketing_touchpoints_preaggregated"
      replica_name   = "{replica}-{shard}"
      version_column = "computed_at"
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

  table "sharded_query_log_archive" {
    order_by     = ["team_id", "event_date", "event_time", "query_id"]
    partition_by = "toYYYYMM(event_date)"
    settings = {
      index_granularity                        = "8192"
      object_serialization_version             = "v3"
      object_shared_data_serialization_version = "map_with_buckets"
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
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.sharded_query_log_archive"
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

  table "sharded_session_replay_features" {
    order_by     = ["team_id", "session_id"]
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
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.session_replay_features"
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

  table "sharded_tophog" {
    order_by     = ["pipeline", "lane", "metric", "timestamp", "key"]
    partition_by = "toYYYYMMDD(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalDay(30)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
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
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.tophog"
      replica_name = "{replica}"
    }
  }

  table "sharded_usage_report_events_preagg" {
    order_by     = ["date", "team_id", "person_mode", "lib", "event"]
    partition_by = "date"
    ttl          = "date + toIntervalDay(14)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
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
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.sharded_usage_report_events_preagg"
      replica_name = "{replica}"
    }
  }

  table "sharded_web_bot_definition" {
    order_by = ["id"]
    settings = {
      index_granularity = "8192"
    }
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
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.sharded_web_bot_definition"
      replica_name = "{replica}"
    }
  }

  table "sharded_web_bounces_dimensional_preaggregated" {
    order_by     = ["team_id", "job_id", "period_bucket", "host", "device_type", "entry_pathname", "end_pathname", "browser", "os", "viewport_width", "viewport_height", "referring_domain", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "country_code", "city_name", "region_code", "region_name", "has_gclid", "has_gad_source_paid_search", "has_fbclid", "mat_metadata_backend", "mat_metadata_loggedIn"]
    partition_by = "toYYYYMMDD(expires_at)"
    ttl          = "toDateTime(expires_at)"
    settings = {
      allow_nullable_key  = "1"
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.web_bounces_dimensional_preaggregated"
      replica_name   = "{replica}"
      version_column = "computed_at"
    }
  }

  table "sharded_web_goals_preaggregated" {
    order_by     = ["team_id", "job_id", "action_id", "time_window_start"]
    partition_by = "toYYYYMMDD(expires_at)"
    ttl          = "toDateTime(expires_at)"
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.web_goals_preaggregated"
      replica_name   = "{replica}"
      version_column = "computed_at"
    }
  }

  table "sharded_web_overview_preaggregated" {
    order_by     = ["team_id", "job_id", "time_window_start"]
    partition_by = "toYYYYMMDD(expires_at)"
    ttl          = "toDateTime(expires_at)"
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.web_overview_preaggregated"
      replica_name   = "{replica}"
      version_column = "computed_at"
    }
  }

  table "sharded_web_stats_dimensional_preaggregated" {
    order_by     = ["team_id", "job_id", "period_bucket", "host", "device_type", "pathname", "entry_pathname", "end_pathname", "browser", "os", "viewport_width", "viewport_height", "referring_domain", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "country_code", "city_name", "region_code", "region_name", "has_gclid", "has_gad_source_paid_search", "has_fbclid", "mat_metadata_backend", "mat_metadata_loggedIn"]
    partition_by = "toYYYYMMDD(expires_at)"
    ttl          = "toDateTime(expires_at)"
    settings = {
      allow_nullable_key  = "1"
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.web_stats_dimensional_preaggregated"
      replica_name   = "{replica}"
      version_column = "computed_at"
    }
  }

  table "sharded_web_stats_frustration_preaggregated" {
    order_by     = ["team_id", "job_id", "breakdown_value", "time_window_start"]
    partition_by = "toYYYYMMDD(expires_at)"
    ttl          = "toDateTime(expires_at)"
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.web_stats_frustration_preaggregated"
      replica_name   = "{replica}"
      version_column = "computed_at"
    }
  }

  table "sharded_web_stats_paths_preaggregated" {
    order_by     = ["team_id", "job_id", "breakdown_value", "time_window_start"]
    partition_by = "toYYYYMMDD(expires_at)"
    ttl          = "toDateTime(expires_at)"
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.web_stats_paths_preaggregated"
      replica_name   = "{replica}"
      version_column = "computed_at"
    }
  }

  table "sharded_web_stats_paths_preaggregated_pathkey" {
    order_by     = ["team_id", "time_window_start", "breakdown_value", "job_id"]
    partition_by = "toYYYYMMDD(expires_at)"
    ttl          = "toDateTime(expires_at)"
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.web_stats_paths_preaggregated_pathkey"
      replica_name   = "{replica}"
      version_column = "computed_at"
    }
  }

  table "sharded_web_stats_preaggregated" {
    order_by     = ["team_id", "job_id", "breakdown_by", "time_window_start", "breakdown_value"]
    partition_by = "toYYYYMMDD(expires_at)"
    ttl          = "toDateTime(expires_at)"
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.web_stats_preaggregated"
      replica_name   = "{replica}"
      version_column = "computed_at"
    }
  }

  table "sharded_web_vitals_paths_preaggregated" {
    order_by     = ["team_id", "job_id", "time_window_start", "path"]
    partition_by = "toYYYYMMDD(expires_at)"
    ttl          = "toDateTime(expires_at)"
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.web_vitals_paths_preaggregated"
      replica_name   = "{replica}"
      version_column = "computed_at"
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

  table "web_bot_definition" {
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
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_bot_definition"
      sharding_key    = "sipHash64(id)"
    }
  }

  table "web_bounces_dimensional_preaggregated" {
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
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_bounces_dimensional_preaggregated"
      sharding_key    = "sipHash64(job_id)"
    }
  }

  table "web_goals_preaggregated" {
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
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_goals_preaggregated"
      sharding_key    = "sipHash64(job_id)"
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

  table "web_pre_aggregated_teams" {
    order_by = ["team_id"]
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "UInt64"
    }
    column "enabled_by" {
      type    = "String"
      default = "'system'"
    }
    column "version" {
      type    = "UInt32"
      default = "toUnixTimestamp(now())"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.web_analytics_team_selection"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  table "web_stats_dimensional_preaggregated" {
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
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_stats_dimensional_preaggregated"
      sharding_key    = "sipHash64(job_id)"
    }
  }

  table "web_stats_frustration_preaggregated" {
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
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_stats_frustration_preaggregated"
      sharding_key    = "sipHash64(job_id)"
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

  table "web_stats_preaggregated" {
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
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_stats_preaggregated"
      sharding_key    = "sipHash64(job_id)"
    }
  }

  table "web_vitals_paths_preaggregated" {
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
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_vitals_paths_preaggregated"
      sharding_key    = "sipHash64(job_id)"
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

  table "writable_error_tracking_fingerprint_issue_state" {
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

  table "writable_events_recent" {
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
    engine "distributed" {
      cluster_name    = "posthog_writable"
      remote_database = "posthog"
      remote_table    = "sharded_events_recent"
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

  table "writable_log_entries" {
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

  table "writable_query_log_archive" {
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
    engine "distributed" {
      cluster_name    = "ops"
      remote_database = "posthog"
      remote_table    = "query_log_archive_buffer"
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

  table "writable_session_replay_events" {
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

  materialized_view "ai_events_json_mv" {
    to_table = "posthog.ai_events"
    query    = <<SQL
SELECT
  uuid,
  event,
  timestamp,
  team_id,
  distinct_id,
  person_id,
  concat(
    '{',
    arrayStringConcat(
      arrayMap(
        x -> concat('"', x.1, '":', x.2),
        arrayFilter(
          x -> ((x.1) NOT IN ('$ai_input', '$ai_output', '$ai_output_choices', '$ai_input_state', '$ai_output_state', '$ai_tools')),
          JSONExtractKeysAndValuesRaw(src.properties)
        )
      ),
      ','
    ),
    '}'
  ) AS properties,
  JSONExtractString(src.properties, '$ai_trace_id') AS trace_id,
  JSONExtract(src.properties, '$ai_session_id', 'Nullable(String)') AS session_id,
  JSONExtract(src.properties, '$ai_parent_id', 'Nullable(String)') AS parent_id,
  JSONExtract(src.properties, '$ai_span_id', 'Nullable(String)') AS span_id,
  JSONExtract(src.properties, '$ai_span_type', 'Nullable(String)') AS span_type,
  JSONExtract(src.properties, '$ai_generation_id', 'Nullable(String)') AS generation_id,
  JSONExtract(src.properties, '$ai_experiment_id', 'Nullable(String)') AS experiment_id,
  JSONExtract(src.properties, '$ai_span_name', 'Nullable(String)') AS span_name,
  JSONExtract(src.properties, '$ai_trace_name', 'Nullable(String)') AS trace_name,
  JSONExtract(src.properties, '$ai_prompt_name', 'Nullable(String)') AS prompt_name,
  JSONExtract(src.properties, '$ai_model', 'Nullable(String)') AS model,
  JSONExtract(src.properties, '$ai_provider', 'Nullable(String)') AS provider,
  JSONExtract(src.properties, '$ai_framework', 'Nullable(String)') AS framework,
  JSONExtract(src.properties, '$ai_total_tokens', 'Nullable(Int64)') AS total_tokens,
  JSONExtract(src.properties, '$ai_input_tokens', 'Nullable(Int64)') AS input_tokens,
  JSONExtract(src.properties, '$ai_output_tokens', 'Nullable(Int64)') AS output_tokens,
  JSONExtract(src.properties, '$ai_text_input_tokens', 'Nullable(Int64)') AS text_input_tokens,
  JSONExtract(src.properties, '$ai_text_output_tokens', 'Nullable(Int64)') AS text_output_tokens,
  JSONExtract(src.properties, '$ai_image_input_tokens', 'Nullable(Int64)') AS image_input_tokens,
  JSONExtract(src.properties, '$ai_image_output_tokens', 'Nullable(Int64)') AS image_output_tokens,
  JSONExtract(src.properties, '$ai_audio_input_tokens', 'Nullable(Int64)') AS audio_input_tokens,
  JSONExtract(src.properties, '$ai_audio_output_tokens', 'Nullable(Int64)') AS audio_output_tokens,
  JSONExtract(src.properties, '$ai_video_input_tokens', 'Nullable(Int64)') AS video_input_tokens,
  JSONExtract(src.properties, '$ai_video_output_tokens', 'Nullable(Int64)') AS video_output_tokens,
  JSONExtract(src.properties, '$ai_reasoning_tokens', 'Nullable(Int64)') AS reasoning_tokens,
  JSONExtract(src.properties, '$ai_cache_read_input_tokens', 'Nullable(Int64)') AS cache_read_input_tokens,
  JSONExtract(src.properties, '$ai_cache_creation_input_tokens', 'Nullable(Int64)') AS cache_creation_input_tokens,
  JSONExtract(src.properties, '$ai_web_search_count', 'Nullable(Int64)') AS web_search_count,
  JSONExtract(src.properties, '$ai_input_cost_usd', 'Nullable(Float64)') AS input_cost_usd,
  JSONExtract(src.properties, '$ai_output_cost_usd', 'Nullable(Float64)') AS output_cost_usd,
  JSONExtract(src.properties, '$ai_total_cost_usd', 'Nullable(Float64)') AS total_cost_usd,
  JSONExtract(src.properties, '$ai_request_cost_usd', 'Nullable(Float64)') AS request_cost_usd,
  JSONExtract(src.properties, '$ai_web_search_cost_usd', 'Nullable(Float64)') AS web_search_cost_usd,
  JSONExtract(src.properties, '$ai_audio_cost_usd', 'Nullable(Float64)') AS audio_cost_usd,
  JSONExtract(src.properties, '$ai_image_cost_usd', 'Nullable(Float64)') AS image_cost_usd,
  JSONExtract(src.properties, '$ai_video_cost_usd', 'Nullable(Float64)') AS video_cost_usd,
  JSONExtract(src.properties, '$ai_latency', 'Nullable(Float64)') AS latency,
  JSONExtract(src.properties, '$ai_time_to_first_token', 'Nullable(Float64)') AS time_to_first_token,
  if((JSONExtractRaw(src.properties, '$ai_is_error') IN ('true', '"true"')), 1, 0) AS is_error,
  JSONExtract(src.properties, '$ai_error', 'Nullable(String)') AS error,
  JSONExtract(src.properties, '$ai_error_type', 'Nullable(String)') AS error_type,
  JSONExtract(src.properties, '$ai_error_normalized', 'Nullable(String)') AS error_normalized,
  nullIf(JSONExtractRaw(src.properties, '$ai_input'), '') AS input,
  nullIf(JSONExtractRaw(src.properties, '$ai_output'), '') AS output,
  nullIf(JSONExtractRaw(src.properties, '$ai_output_choices'), '') AS output_choices,
  nullIf(JSONExtractRaw(src.properties, '$ai_input_state'), '') AS input_state,
  nullIf(JSONExtractRaw(src.properties, '$ai_output_state'), '') AS output_state,
  nullIf(JSONExtractRaw(src.properties, '$ai_tools'), '') AS tools,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_ai_events_json AS src
SQL

    column "uuid" {
      type = "UUID"
    }
    column "event" {
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
    column "person_id" {
      type = "UUID"
    }
    column "properties" {
      type = "String"
    }
    column "trace_id" {
      type = "String"
    }
    column "session_id" {
      type = "Nullable(String)"
    }
    column "parent_id" {
      type = "Nullable(String)"
    }
    column "span_id" {
      type = "Nullable(String)"
    }
    column "span_type" {
      type = "Nullable(String)"
    }
    column "generation_id" {
      type = "Nullable(String)"
    }
    column "experiment_id" {
      type = "Nullable(String)"
    }
    column "span_name" {
      type = "Nullable(String)"
    }
    column "trace_name" {
      type = "Nullable(String)"
    }
    column "prompt_name" {
      type = "Nullable(String)"
    }
    column "model" {
      type = "Nullable(String)"
    }
    column "provider" {
      type = "Nullable(String)"
    }
    column "framework" {
      type = "Nullable(String)"
    }
    column "total_tokens" {
      type = "Nullable(Int64)"
    }
    column "input_tokens" {
      type = "Nullable(Int64)"
    }
    column "output_tokens" {
      type = "Nullable(Int64)"
    }
    column "text_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "text_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "image_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "image_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "audio_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "audio_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "video_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "video_output_tokens" {
      type = "Nullable(Int64)"
    }
    column "reasoning_tokens" {
      type = "Nullable(Int64)"
    }
    column "cache_read_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "cache_creation_input_tokens" {
      type = "Nullable(Int64)"
    }
    column "web_search_count" {
      type = "Nullable(Int64)"
    }
    column "input_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "output_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "total_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "request_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "web_search_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "audio_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "image_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "video_cost_usd" {
      type = "Nullable(Float64)"
    }
    column "latency" {
      type = "Nullable(Float64)"
    }
    column "time_to_first_token" {
      type = "Nullable(Float64)"
    }
    column "is_error" {
      type = "UInt8"
    }
    column "error" {
      type = "Nullable(String)"
    }
    column "error_type" {
      type = "Nullable(String)"
    }
    column "error_normalized" {
      type = "Nullable(String)"
    }
    column "input" {
      type = "Nullable(String)"
    }
    column "output" {
      type = "Nullable(String)"
    }
    column "output_choices" {
      type = "Nullable(String)"
    }
    column "input_state" {
      type = "Nullable(String)"
    }
    column "output_state" {
      type = "Nullable(String)"
    }
    column "tools" {
      type = "Nullable(String)"
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

  materialized_view "error_tracking_fingerprint_issue_state_mv" {
    to_table = "posthog.writable_error_tracking_fingerprint_issue_state"
    query    = <<SQL
SELECT
  team_id,
  fingerprint,
  issue_id,
  issue_name,
  issue_description,
  issue_status,
  assigned_user_id,
  assigned_role_id,
  first_seen,
  is_deleted,
  version,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_error_tracking_fingerprint_issue_state
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
    column "issue_name" {
      type = "Nullable(String)"
    }
    column "issue_description" {
      type = "Nullable(String)"
    }
    column "issue_status" {
      type = "String"
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

  materialized_view "events_json_mv" {
    to_table = "posthog.writable_events"
    query    = <<SQL
SELECT
  uuid,
  event,
  properties,
  timestamp,
  team_id,
  distinct_id,
  elements_chain,
  created_at,
  person_id,
  person_created_at,
  person_properties,
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
  dmat_string_0,
  dmat_string_1,
  dmat_string_2,
  dmat_string_3,
  dmat_string_4,
  dmat_string_5,
  dmat_string_6,
  dmat_string_7,
  dmat_string_8,
  dmat_string_9,
  _timestamp,
  _offset,
  arrayMap(
    i -> (_headers.value[i]),
    arrayFilter(
      i -> ((_headers.name[i]) = 'kafka-consumer-breadcrumbs'),
      arrayEnumerate(_headers.name)
    )
  ) AS consumer_breadcrumbs
FROM posthog.kafka_events_json
SQL

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
    query    = <<SQL
SELECT
  uuid,
  event,
  properties,
  timestamp,
  team_id,
  distinct_id,
  elements_chain,
  created_at,
  person_id,
  person_created_at,
  person_properties,
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
  _timestamp,
  _offset
FROM posthog.sharded_events
SQL

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

  materialized_view "hog_invocation_results_mv" {
    to_table = "posthog.hog_invocation_results_data"
    query    = <<SQL
SELECT
  team_id,
  function_kind,
  function_id,
  invocation_id,
  parent_run_id,
  status,
  attempts,
  is_retry,
  scheduled_at,
  if(
    first_scheduled_at = toDateTime64('1970-01-01 00:00:00', 6, 'UTC'),
    scheduled_at,
    first_scheduled_at
  ) AS first_scheduled_at,
  started_at,
  finished_at,
  duration_ms,
  error_kind,
  error_message,
  event_uuid,
  distinct_id,
  person_id,
  invocation_globals,
  version,
  is_deleted,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_hog_invocation_results
SQL

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

  materialized_view "ingestion_warnings_v2_mv" {
    to_table = "posthog.ingestion_warnings_v2"
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
FROM posthog.kafka_ingestion_warnings_v2
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

  materialized_view "kafka_logs34_avro_mv" {
    to_table = "posthog.logs34"
    query    = <<SQL
SELECT
  kafka_logs_avro.* EXCEPT(created_at, attribute_values, attribute_keys, attributes, attributes_map_str, attributes_map_float, attributes_map_datetime, resource_attributes, bytes_uncompressed),
  mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
  mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
  toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
  observed_timestamp
  + toIntervalDay(
    toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(15))
  ) AS original_expiry_timestamp,
  _partition,
  _topic,
  _offset,
  toInt64OrDefault(_headers.value[indexOf(_headers.name, 'record_count')], toInt64(1)) AS _record_count,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_uncompressed')]) / _record_count AS _bytes_uncompressed,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_compressed')]) / _record_count AS _bytes_compressed
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
  }

  materialized_view "kafka_logs_avro_billing_metrics_mv" {
    to_table = "posthog.logs_billing_metrics"
    query    = <<SQL
SELECT
  team_id,
  time_bucket,
  service_name,
  sumSimpleState(_bytes_uncompressed) AS bytes_uncompressed,
  sumSimpleState(_bytes_compressed) AS bytes_compressed,
  sumSimpleState(1) AS record_count
FROM
  (
    SELECT
      team_id,
      toStartOfInterval(timestamp, toIntervalMinute(1)) AS time_bucket,
      service_name AS service_name,
      _bytes_uncompressed,
      _bytes_compressed
    FROM posthog.logs34
  )
GROUP BY
  team_id, time_bucket, service_name
SQL

    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "bytes_uncompressed" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "bytes_compressed" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "record_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
  }

  materialized_view "kafka_logs_avro_kafka_metrics_mv" {
    to_table = "posthog.logs_kafka_metrics"
    query    = <<SQL
SELECT
  _partition,
  _topic,
  maxSimpleState(_offset) AS max_offset,
  maxSimpleState(observed_timestamp) AS max_observed_timestamp,
  maxSimpleState(timestamp) AS max_timestamp,
  maxSimpleState(now()) AS max_created_at,
  maxSimpleState(now() - observed_timestamp) AS max_lag
FROM posthog.logs34
GROUP BY
  _partition, _topic
SQL

    column "_partition" {
      type = "UInt32"
    }
    column "_topic" {
      type = "String"
    }
    column "max_offset" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "max_observed_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6))"
    }
    column "max_created_at" {
      type = "SimpleAggregateFunction(max, DateTime)"
    }
    column "max_lag" {
      type = "SimpleAggregateFunction(max, Decimal(18, 6))"
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

  materialized_view "logs32_to_log_attributes" {
    to_table = "posthog.log_attributes"
    query    = <<SQL
SELECT
  team_id,
  time_bucket,
  original_expiry_time_bucket,
  service_name,
  resource_fingerprint,
  attribute_key,
  attribute_value,
  attribute_type,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
      toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
      service_name AS service_name,
      resource_fingerprint,
      mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
      arrayJoin(attributes) AS attribute,
      'log' AS attribute_type,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.logs32
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, attributes
  )
SQL

    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_fingerprint" {
      type = "UInt64"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type = "String"
    }
    column "attribute_type" {
      type = "LowCardinality(String)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
  }

  materialized_view "logs32_to_resource_attributes" {
    to_table = "posthog.log_attributes"
    query    = <<SQL
SELECT
  team_id,
  time_bucket,
  original_expiry_time_bucket,
  service_name,
  resource_fingerprint,
  attribute_key,
  attribute_value,
  attribute_type,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
      toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
      service_name AS service_name,
      resource_fingerprint,
      arrayJoin(resource_attributes) AS attribute,
      'resource' AS attribute_type,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.logs32
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, resource_attributes
  )
SQL

    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_fingerprint" {
      type = "UInt64"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type = "String"
    }
    column "attribute_type" {
      type = "LowCardinality(String)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
  }

  materialized_view "logs34_to_log_attributes" {
    to_table = "posthog.log_attributes2"
    query    = <<SQL
SELECT
  team_id,
  time_bucket,
  original_expiry_time_bucket,
  service_name,
  resource_fingerprint,
  attribute_key,
  attribute_value,
  attribute_type,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
      toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
      service_name AS service_name,
      resource_fingerprint,
      mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
      arrayJoin(attributes) AS attribute,
      'log' AS attribute_type,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.logs34
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, attributes
  )
SQL

    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_fingerprint" {
      type = "UInt64"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type = "String"
    }
    column "attribute_type" {
      type = "LowCardinality(String)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
  }

  materialized_view "logs34_to_log_attributes3" {
    to_table = "posthog.log_attributes3"
    query    = <<SQL
SELECT
  team_id,
  time_bucket,
  original_expiry_time_bucket,
  service_name,
  resource_fingerprint,
  attribute_key,
  attribute_value,
  attribute_type,
  severity_text,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
      toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
      service_name AS service_name,
      resource_fingerprint,
      severity_text AS severity_text,
      mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
      arrayJoin(attributes) AS attribute,
      'log' AS attribute_type,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.logs34
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, severity_text, attributes
  )
SQL

    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_fingerprint" {
      type = "UInt64"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type = "String"
    }
    column "attribute_type" {
      type = "LowCardinality(String)"
    }
    column "severity_text" {
      type = "LowCardinality(String)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
  }

  materialized_view "logs34_to_resource_attributes" {
    to_table = "posthog.log_attributes2"
    query    = <<SQL
SELECT
  team_id,
  time_bucket,
  original_expiry_time_bucket,
  service_name,
  resource_fingerprint,
  attribute_key,
  attribute_value,
  attribute_type,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
      toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
      service_name AS service_name,
      resource_fingerprint,
      arrayJoin(resource_attributes) AS attribute,
      'resource' AS attribute_type,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.logs34
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, resource_attributes
  )
SQL

    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_fingerprint" {
      type = "UInt64"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type = "String"
    }
    column "attribute_type" {
      type = "LowCardinality(String)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
  }

  materialized_view "logs34_to_resource_attributes3" {
    to_table = "posthog.log_attributes3"
    query    = <<SQL
SELECT
  team_id,
  time_bucket,
  original_expiry_time_bucket,
  service_name,
  resource_fingerprint,
  attribute_key,
  attribute_value,
  attribute_type,
  severity_text,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
      toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
      service_name AS service_name,
      resource_fingerprint,
      severity_text AS severity_text,
      arrayJoin(resource_attributes) AS attribute,
      'resource' AS attribute_type,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.logs34
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, severity_text, resource_attributes
  )
SQL

    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_fingerprint" {
      type = "UInt64"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type = "String"
    }
    column "attribute_type" {
      type = "LowCardinality(String)"
    }
    column "severity_text" {
      type = "LowCardinality(String)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
  }

  materialized_view "message_assets_mv" {
    to_table = "posthog.message_assets_data"
    query    = <<SQL
SELECT
  team_id,
  function_kind,
  function_id,
  parent_run_id,
  invocation_id,
  action_id,
  kind,
  distinct_id,
  person_id,
  recipient,
  subject,
  status,
  sent_at,
  version,
  is_deleted,
  html,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_message_assets
SQL

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
      type = "Nullable(DateTime)"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_partition" {
      type = "UInt64"
    }
  }

  materialized_view "ops_query_log_archive_mv" {
    to_table = "posthog.writable_query_log_archive"
    query    = <<SQL
SELECT
  hostname,
  user,
  query_id,
  initial_query_id,
  is_initial_query,
  type,
  event_date,
  event_time,
  event_time_microseconds,
  query_start_time,
  query_start_time_microseconds,
  query_duration_ms,
  read_rows,
  read_bytes,
  written_rows,
  written_bytes,
  result_rows,
  result_bytes,
  memory_usage,
  peak_threads_usage,
  current_database,
  query,
  formatted_query,
  normalized_query_hash,
  query_kind,
  exception_code,
  exception,
  stack_trace,
  JSONExtractInt(log_comment, 'team_id') AS team_id,
  if(isValidJSON(log_comment), log_comment, '{}') AS log_comment,
  ProfileEvents
FROM system.query_log
WHERE type != 'QueryStart'
SQL

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
      type = "String"
    }
    column "ProfileEvents" {
      type = "Map(LowCardinality(String), UInt64)"
    }
  }

  materialized_view "performance_events_mv" {
    to_table = "posthog.writeable_performance_events"
    query    = <<SQL
SELECT
  uuid,
  session_id,
  window_id,
  pageview_id,
  distinct_id,
  timestamp,
  time_origin,
  entry_type,
  name,
  team_id,
  current_url,
  start_time,
  duration,
  redirect_start,
  redirect_end,
  worker_start,
  fetch_start,
  domain_lookup_start,
  domain_lookup_end,
  connect_start,
  secure_connection_start,
  connect_end,
  request_start,
  response_start,
  response_end,
  decoded_body_size,
  encoded_body_size,
  initiator_type,
  next_hop_protocol,
  render_blocking_status,
  response_status,
  transfer_size,
  largest_contentful_paint_element,
  largest_contentful_paint_render_time,
  largest_contentful_paint_load_time,
  largest_contentful_paint_size,
  largest_contentful_paint_id,
  largest_contentful_paint_url,
  dom_complete,
  dom_content_loaded_event,
  dom_interactive,
  load_event_end,
  load_event_start,
  redirect_count,
  navigation_type,
  unload_event_end,
  unload_event_start,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_performance_events
SQL

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

  materialized_view "person_distinct_id_mv" {
    to_table = "posthog.person_distinct_id"
    query    = <<SQL
SELECT
  distinct_id,
  person_id,
  team_id,
  coalesce(_sign, if(is_deleted = 0, 1, -1)) AS _sign,
  _timestamp,
  _offset
FROM posthog.kafka_person_distinct_id
SQL

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

  materialized_view "person_overrides_mv" {
    to_table = "posthog.person_overrides"
    query    = <<SQL
SELECT team_id, old_person_id, override_person_id, merged_at, oldest_event, version
FROM posthog.kafka_person_overrides
SQL

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

  materialized_view "posthog_document_embeddings_text_embedding_3_large_3072_mv" {
    to_table = "posthog.writable_posthog_document_embeddings_text_embedding_3_large_3072"
    query    = <<SQL
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
  _partition
FROM posthog.sharded_posthog_document_embeddings_buffer
WHERE model_name = 'text-embedding-3-large-3072'
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
    query    = <<SQL
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
  _partition
FROM posthog.sharded_posthog_document_embeddings_buffer
WHERE model_name = 'text-embedding-3-small-1536'
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

  materialized_view "property_values_mv" {
    to_table = "posthog.property_values"
    query    = <<SQL
SELECT
  team_id,
  property_type,
  property_key,
  property_value,
  property_count,
  coalesce(_timestamp, now()) AS last_seen
FROM posthog.kafka_property_values
SQL

    column "team_id" {
      type = "Int64"
    }
    column "property_type" {
      type = "LowCardinality(String)"
    }
    column "property_key" {
      type = "String"
    }
    column "property_value" {
      type = "String"
    }
    column "property_count" {
      type = "UInt64"
    }
    column "last_seen" {
      type = "DateTime"
    }
  }

  materialized_view "raw_sessions_mv" {
    to_table = "posthog.writable_raw_sessions"
    query    = <<SQL
SELECT
  team_id,
  toUInt128(toUUID(`$session_id`)) AS session_id_v7,
  argMaxState(distinct_id, timestamp) AS distinct_id,
  min(timestamp) AS min_timestamp,
  max(timestamp) AS max_timestamp,
  max(coalesce(inserted_at, now64())) AS max_inserted_at,
  groupUniqArray(nullIf(JSONExtractString(properties, '$current_url'), '')) AS urls,
  argMinState(JSONExtractString(properties, '$current_url'), timestamp) AS entry_url,
  argMaxState(JSONExtractString(properties, '$current_url'), timestamp) AS end_url,
  argMaxState(JSONExtractString(properties, '$external_click_url'), timestamp) AS last_external_click_url,
  argMinState(JSONExtractString(properties, '$browser'), timestamp) AS initial_browser,
  argMinState(JSONExtractString(properties, '$browser_version'), timestamp) AS initial_browser_version,
  argMinState(JSONExtractString(properties, '$os'), timestamp) AS initial_os,
  argMinState(JSONExtractString(properties, '$os_version'), timestamp) AS initial_os_version,
  argMinState(JSONExtractString(properties, '$device_type'), timestamp) AS initial_device_type,
  argMinState(JSONExtractInt(properties, '$viewport_width'), timestamp) AS initial_viewport_width,
  argMinState(JSONExtractInt(properties, '$viewport_height'), timestamp) AS initial_viewport_height,
  argMinState(JSONExtractString(properties, '$geoip_country_code'), timestamp) AS initial_geoip_country_code,
  argMinState(JSONExtractString(properties, '$geoip_subdivision_1_code'), timestamp) AS initial_geoip_subdivision_1_code,
  argMinState(JSONExtractString(properties, '$geoip_subdivision_1_name'), timestamp) AS initial_geoip_subdivision_1_name,
  argMinState(JSONExtractString(properties, '$geoip_subdivision_city_name'), timestamp) AS initial_geoip_subdivision_city_name,
  argMinState(JSONExtractString(properties, '$geoip_time_zone'), timestamp) AS initial_geoip_time_zone,
  argMinState(JSONExtractString(properties, '$referring_domain'), timestamp) AS initial_referring_domain,
  argMinState(JSONExtractString(properties, 'utm_source'), timestamp) AS initial_utm_source,
  argMinState(JSONExtractString(properties, 'utm_campaign'), timestamp) AS initial_utm_campaign,
  argMinState(JSONExtractString(properties, 'utm_medium'), timestamp) AS initial_utm_medium,
  argMinState(JSONExtractString(properties, 'utm_term'), timestamp) AS initial_utm_term,
  argMinState(JSONExtractString(properties, 'utm_content'), timestamp) AS initial_utm_content,
  argMinState(JSONExtractString(properties, 'gclid'), timestamp) AS initial_gclid,
  argMinState(JSONExtractString(properties, 'gad_source'), timestamp) AS initial_gad_source,
  argMinState(JSONExtractString(properties, 'gclsrc'), timestamp) AS initial_gclsrc,
  argMinState(JSONExtractString(properties, 'dclid'), timestamp) AS initial_dclid,
  argMinState(JSONExtractString(properties, 'gbraid'), timestamp) AS initial_gbraid,
  argMinState(JSONExtractString(properties, 'wbraid'), timestamp) AS initial_wbraid,
  argMinState(JSONExtractString(properties, 'fbclid'), timestamp) AS initial_fbclid,
  argMinState(JSONExtractString(properties, 'msclkid'), timestamp) AS initial_msclkid,
  argMinState(JSONExtractString(properties, 'twclid'), timestamp) AS initial_twclid,
  argMinState(JSONExtractString(properties, 'li_fat_id'), timestamp) AS initial_li_fat_id,
  argMinState(JSONExtractString(properties, 'mc_cid'), timestamp) AS initial_mc_cid,
  argMinState(JSONExtractString(properties, 'igshid'), timestamp) AS initial_igshid,
  argMinState(JSONExtractString(properties, 'ttclid'), timestamp) AS initial_ttclid,
  argMinState(JSONExtractString(properties, 'epik'), timestamp) AS initial_epik,
  argMinState(JSONExtractString(properties, 'qclid'), timestamp) AS initial_qclid,
  argMinState(JSONExtractString(properties, 'sccid'), timestamp) AS initial_sccid,
  argMinState(JSONExtractString(properties, '_kx'), timestamp) AS initial__kx,
  argMinState(JSONExtractString(properties, 'irclid'), timestamp) AS initial_irclid,
  sumIf(1, event = '$pageview') AS pageview_count,
  uniqState(CAST(if(event = '$pageview', uuid, NULL), 'Nullable(UUID)')) AS pageview_uniq,
  sumIf(1, event = '$autocapture') AS autocapture_count,
  uniqState(CAST(if(event = '$autocapture', uuid, NULL), 'Nullable(UUID)')) AS autocapture_uniq,
  sumIf(1, event = '$screen') AS screen_count,
  uniqState(CAST(if(event = '$screen', uuid, NULL), 'Nullable(UUID)')) AS screen_uniq,
  false AS maybe_has_session_replay,
  uniqUpToState(
    1
  )(CAST(if((event = '$pageview') OR (event = '$screen') OR (event = '$autocapture'), uuid, NULL), 'Nullable(UUID)')) AS page_screen_autocapture_uniq_up_to,
  argMinState(
    accurateCastOrNull(
      replaceRegexpAll(
        nullIf(nullIf(JSONExtractRaw(properties, '$web_vitals_LCP_value'), ''), 'null'),
        '^"|"$',
        ''
      ),
      'Float64'
    ),
    timestamp
  ) AS vitals_lcp
FROM posthog.sharded_events
WHERE
  bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(`$session_id`, 'UUID')), 76), 15) = 7
GROUP BY
  team_id, toStartOfHour(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000))), cityHash64(session_id_v7), session_id_v7
SQL

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

  materialized_view "sessions_mv" {
    to_table = "posthog.writable_sessions"
    query    = <<SQL
SELECT
  `$session_id` AS session_id,
  team_id,
  any(distinct_id) AS distinct_id,
  min(timestamp) AS min_timestamp,
  max(timestamp) AS max_timestamp,
  groupUniqArray(replaceRegexpAll(JSONExtractRaw(properties, '$current_url'), '^"|"$', '')) AS urls,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, '$current_url'), '^"|"$', ''), timestamp) AS entry_url,
  argMaxState(replaceRegexpAll(JSONExtractRaw(properties, '$current_url'), '^"|"$', ''), timestamp) AS exit_url,
  argMinState(
    replaceRegexpAll(JSONExtractRaw(properties, '$referring_domain'), '^"|"$', ''),
    timestamp
  ) AS initial_referring_domain,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_source'), '^"|"$', ''), timestamp) AS initial_utm_source,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_campaign'), '^"|"$', ''), timestamp) AS initial_utm_campaign,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_medium'), '^"|"$', ''), timestamp) AS initial_utm_medium,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_term'), '^"|"$', ''), timestamp) AS initial_utm_term,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_content'), '^"|"$', ''), timestamp) AS initial_utm_content,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gclid'), '^"|"$', ''), timestamp) AS initial_gclid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gad_source'), '^"|"$', ''), timestamp) AS initial_gad_source,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gclsrc'), '^"|"$', ''), timestamp) AS initial_gclsrc,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'dclid'), '^"|"$', ''), timestamp) AS initial_dclid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gbraid'), '^"|"$', ''), timestamp) AS initial_gbraid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'wbraid'), '^"|"$', ''), timestamp) AS initial_wbraid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'fbclid'), '^"|"$', ''), timestamp) AS initial_fbclid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'msclkid'), '^"|"$', ''), timestamp) AS initial_msclkid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'twclid'), '^"|"$', ''), timestamp) AS initial_twclid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'li_fat_id'), '^"|"$', ''), timestamp) AS initial_li_fat_id,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'mc_cid'), '^"|"$', ''), timestamp) AS initial_mc_cid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'igshid'), '^"|"$', ''), timestamp) AS initial_igshid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'ttclid'), '^"|"$', ''), timestamp) AS initial_ttclid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'epik'), '^"|"$', ''), timestamp) AS initial_epik,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'qclid'), '^"|"$', ''), timestamp) AS initial_qclid,
  argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'sccid'), '^"|"$', ''), timestamp) AS initial_sccid,
  sumMap(CAST(([event], [1]), 'Map(String, UInt64)')) AS event_count_map,
  sumIf(1, event = '$pageview') AS pageview_count,
  sumIf(1, event = '$autocapture') AS autocapture_count
FROM posthog.sharded_events
WHERE
  (`$session_id` IS NOT NULL)
AND
  (`$session_id` != '')
AND
  (team_id IN (1, 2, 13610, 19279, 21173, 29929, 32050, 9910, 11775, 21129, 31490))
GROUP BY
  `$session_id`, team_id
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

  view "custom_metrics" {
    query = <<SQL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_test
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_replication_queue
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_events_recent_lag
UNION ALL
SELECT *
FROM posthog.custom_metrics_counters
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_server_crash
UNION ALL
SELECT *
FROM posthog.custom_metrics_table_sizes
SQL

  }

  view "custom_metrics_counters" {
    query = <<SQL
SELECT
  name,
  mapSort(labels) AS labels,
  sum(increment) AS value,
  '' AS help,
  'counter' AS type
FROM posthog.custom_metrics_counter_events
GROUP BY
  name, type, labels
ORDER BY name ASC, type ASC, labels ASC
SQL

  }

  view "custom_metrics_events_recent_lag" {
    query = <<SQL
SELECT
  'ClickHouseCustomMetric_EventsRecentIngestionLag' AS name,
  map('instance', hostname()) AS labels,
  dateDiff('second', max(timestamp), now()) AS value,
  'The number of seconds that have passed since the most recent event was inserted into events_recent table' AS help,
  'gauge' AS type
FROM posthog.events_recent
WHERE
  (team_id IN [])
AND
  (event IN ('$heartbeat'))
AND
  (timestamp < (now() + toIntervalMinute(3)))
AND
  (inserted_at > (now() - toIntervalHour(3)))
GROUP BY
  event
SQL

  }

  view "custom_metrics_replication_queue" {
    query = <<SQL
WITH
  ['ClickHouseCustomMetric_ReplicationQueueStuckEntries', 'ClickHouseCustomMetric_ReplicationQueueMaxPostponedEntrySeconds', 'ClickHouseCustomMetric_ReplicationQueueMaxErrorEntrySeconds'] AS names,
  [toInt64(countIf(create_time < (now() - toIntervalDay(15)))), maxIf(dateDiff('seconds', create_time, last_postpone_time), last_postpone_time != '1970-01-01'), maxIf(dateDiff('seconds', create_time, last_exception_time), (last_exception_time != '1970-01-01') AND (last_exception_time > (now() - toIntervalMinute(5))))] AS values,
  ['Number of entries that have been in the replication queue for more than 15 days', 'Maximum number of seconds that an entry has been postponed', 'Maximum number of seconds that an entry has been in error'] AS descriptions,
  ['gauge', 'gauge', 'gauge'] AS types,
  arrayJoin(arrayZip(names, values, descriptions, types)) AS tpl
SELECT
  tpl.1 AS name,
  map('table', `table`, 'instance', hostname()) AS labels,
  tpl.2 AS value,
  tpl.3 AS help,
  tpl.4 AS type
FROM system.replication_queue
GROUP BY
  `table`
HAVING
  value > 0
SQL

  }

  view "custom_metrics_server_crash" {
    query = <<SQL
SELECT
  'ClickHouseCustomMetric_ServerCrash' AS name,
  map('instance', hostname()) AS labels,
  count() AS value,
  'Number of server crashes for current date' AS help,
  'gauge' AS type
FROM system.crash_log
WHERE event_date = today()
GROUP BY
  hostname()
SQL

  }

  view "custom_metrics_table_sizes" {
    query = <<SQL
SELECT
  'ClickHouseCustomMetric_TableTotalBytes' AS name,
  map('instance', hostname(), 'database', database, 'table', `table`) AS labels,
  CAST(total_bytes, 'Float64') AS value,
  'Size of a database table on a given node (need a sum for sharded)' AS help,
  'gauge' AS type
FROM system.tables
WHERE
  (database NOT IN ('INFORMATION_SCHEMA', 'information_schema'))
AND
  (total_bytes IS NOT NULL)
SQL

  }

  view "custom_metrics_test" {
    query = <<SQL
SELECT
  'ClickHouseCustomMetric_Test' AS name,
  map('instance', hostname()) AS labels,
  1 AS value,
  'Test to check that the metric endpoint is working' AS help,
  'gauge' AS type
SQL

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
  new_persons AS (SELECT id, max(version) AS version, argMax(_timestamp, person.version) AS _timestamp2 FROM posthog.person WHERE (team_id = {team_id: Int64}) AND (id IN (SELECT id FROM posthog.person WHERE (team_id = {team_id: Int64}) AND (_timestamp >= {interval_start: DateTime64}) AND (_timestamp < {interval_end: DateTime64}))) GROUP BY id HAVING (_timestamp2 >= {interval_start: DateTime64}) AND (_timestamp2 < {interval_end: DateTime64})),
  new_distinct_ids AS (SELECT argMax(person_id, person_distinct_id2.version) AS person_id FROM posthog.person_distinct_id2 WHERE (team_id = {team_id: Int64}) AND (distinct_id IN (SELECT distinct_id FROM posthog.person_distinct_id2 WHERE (team_id = {team_id: Int64}) AND (_timestamp >= {interval_start: DateTime64}) AND (_timestamp < {interval_end: DateTime64}))) GROUP BY distinct_id HAVING (argMax(_timestamp, person_distinct_id2.version) >= {interval_start: DateTime64}) AND (argMax(_timestamp, person_distinct_id2.version) < {interval_end: DateTime64})),
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

  dictionary "channel_definition_dict" {
    primary_key = ["domain", "kind"]
    lifetime {
      min = 3000
      max = 3600
    }
    attribute "domain" {
      type = "String"
    }
    attribute "kind" {
      type = "String"
    }
    attribute "domain_type" {
      type = "Nullable(String)"
    }
    attribute "type_if_paid" {
      type = "Nullable(String)"
    }
    attribute "type_if_organic" {
      type = "Nullable(String)"
    }
    source "clickhouse" {
      user  = "default"
      table = "channel_definition"
    }
    layout "complex_key_hashed" {
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

  dictionary "web_pre_aggregated_teams_dict" {
    primary_key = ["team_id"]
    lifetime {
      min = 3000
      max = 3600
    }
    attribute "team_id" {
      type = "UInt64"
    }
    source "clickhouse" {
      user  = "default"
      query = "SELECT     team_id FROM     `posthog`.`web_pre_aggregated_teams` FINAL WHERE version > 0"
    }
    layout "hashed" {
    }
  }
}
