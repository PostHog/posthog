database "posthog" {
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
      remote_table    = "ai_events"
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

  table "async_deletion_run" {
    column "id" {
      type = "UInt64"
    }
    column "deletion_type" {
      type = "UInt8"
    }
    column "key" {
      type = "String"
    }
    column "group_type_index" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    engine "join" {
      strictness = "ANY"
      type       = "LEFT"
      keys       = ["team_id", "deletion_type", "key"]
    }
  }

  table "asyncdeletion" {
    order_by     = ["deletion_type", "delete_verified_at"]
    partition_by = "toYYYYMM(created_at)"
    settings = {
      index_granularity = "8192"
    }
    column "id" {
      type = "UInt64"
    }
    column "deletion_type" {
      type = "UInt8"
    }
    column "key" {
      type = "String"
    }
    column "group_type_index" {
      type = "UInt64"
    }
    column "created_at" {
      type = "DateTime"
    }
    column "delete_verified_at" {
      type = "DateTime"
    }
    column "created_by_id" {
      type = "UInt64"
    }
    column "team_id" {
      type = "UInt64"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/asyncdeletion"
      replica_name = "{replica}-{shard}"
    }
  }

  table "billing_usage_records" {
    column "schema_version" {
      type = "UInt8"
    }
    column "record_id" {
      type = "String"
    }
    column "producer_id" {
      type = "LowCardinality(String)"
    }
    column "team_id" {
      type = "Int64"
    }
    column "organization_id" {
      type = "UUID"
    }
    column "usage_key" {
      type = "LowCardinality(String)"
    }
    column "unit" {
      type = "LowCardinality(String)"
    }
    column "quantity" {
      type = "Int64"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "inserted_at" {
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
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_billing_usage_records"
      sharding_key    = "cityHash64(team_id)"
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
    order_by     = ["run_id", "team_id", "person_id"]
    partition_by = "run_id"
    ttl          = "created_at + toIntervalDay(14)"
    settings = {
      index_granularity   = "8192"
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
    order_by     = ["run_id", "team_id", "distinct_id"]
    partition_by = "run_id"
    ttl          = "created_at + toIntervalDay(14)"
    settings = {
      index_granularity   = "8192"
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
    order_by     = ["run_id", "team_id", "distinct_id"]
    partition_by = "run_id"
    ttl          = "created_at + toIntervalDay(14)"
    settings = {
      index_granularity   = "8192"
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
    order_by     = ["run_id", "team_id", "person_id"]
    partition_by = "run_id"
    ttl          = "created_at + toIntervalDay(14)"
    settings = {
      index_granularity   = "8192"
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

  table "cohortpeople" {
    order_by     = ["team_id", "cohort_id", "person_id"]
    partition_by = "team_id % 16"
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.cohortpeople_new_partitioned"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
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
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_partition" {
      type = "UInt64"
    }
    column "inserted_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    column "_timestamp_ms" {
      type = "DateTime64(3)"
    }
    engine "distributed" {
      cluster_name    = "batch_exports"
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
      remote_table    = "sharded_posthog_document_embeddings"
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
    column "query_kind" {
      type = "String"
    }
    column "thread_ids" {
      type = "Array(UInt64)"
    }
    column "ProfileEvents" {
      type = "Map(String, UInt64)"
    }
    column "Settings" {
      type = "Map(String, String)"
    }
    column "current_database" {
      type = "String"
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
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "mat_metadata_backend" {
      type    = "String"
      comment = "column_materializer::properties::metadata.backend"
    }
    column "mat_metadata_loggedIn" {
      type    = "String"
      comment = "column_materializer::properties::metadata.loggedIn"
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
    column "properties_group_feature_flags" {
      type = "Map(String, String)"
    }
    column "is_deleted" {
      type = "Bool"
    }
    column "person_properties_map_custom" {
      type = "Map(String, String)"
    }
    column "mat_$ai_trace_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_trace_id"
    }
    column "$session_id_uuid" {
      type = "Nullable(UInt128)"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
    column "properties_group_ai" {
      type = "Map(String, String)"
    }
    column "mat_historical_migration" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::historical_migration"
    }
    column "mat_$ai_session_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_session_id"
    }
    column "mat_$ai_is_error" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_is_error"
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
    column "historical_migration" {
      type = "Bool"
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
    column "inserted_at" {
      type = "DateTime64(6, 'UTC')"
    }
    engine "distributed" {
      cluster_name    = "batch_exports"
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

  table "flag_evaluations" {
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
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_ingestion_warnings"
      sharding_key    = "rand()"
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
    column "quick_back_count" {
      type = "Int64"
    }
    column "page_visit_count" {
      type = "Int64"
    }
    column "visited_urls" {
      type = "Array(String)"
    }
    column "console_error_count" {
      type = "Int64"
    }
    column "console_error_after_click_count" {
      type = "Int64"
    }
    column "network_request_count" {
      type = "Int64"
    }
    column "network_failed_request_count" {
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
    column "max_scroll_y" {
      type = "Float64"
    }
    column "click_target_ids" {
      type = "Array(Int64)"
    }
    column "text_selection_count" {
      type = "Int64"
    }
    column "is_deleted" {
      type = "UInt8"
    }
    engine "kafka" {
      collection = "msk_cluster"
      topic_list = "clickhouse_session_replay_features"
      group_name = "group1"
      format     = "JSONEachRow"
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

  table "log_entries_distributed" {
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
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "log_entries_data"
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

  table "metrics_query_log" {
    order_by     = ["toDate(timestamp)", "team_id", "query_type"]
    partition_by = "toYYYYMM(timestamp)"
    settings = {
      index_granularity = "8192"
    }
    column "host" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime"
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
    column "result_rows" {
      type = "UInt64"
    }
    column "result_bytes" {
      type = "UInt64"
    }
    column "memory_usage" {
      type = "UInt64"
    }
    column "is_initial_query" {
      type = "UInt8"
    }
    column "exception_code" {
      type = "Int32"
    }
    column "team_id" {
      type = "Int64"
    }
    column "team_events_last_month" {
      type = "UInt64"
    }
    column "user_id" {
      type = "Int64"
    }
    column "kind" {
      type = "String"
    }
    column "query_type" {
      type = "String"
    }
    column "client_query_id" {
      type = "String"
    }
    column "id" {
      type = "String"
    }
    column "route_id" {
      type = "String"
    }
    column "query_time_range_days" {
      type = "Int64"
    }
    column "has_joins" {
      type = "UInt8"
    }
    column "has_json_operations" {
      type = "UInt8"
    }
    column "filter_by_type" {
      type = "Array(String)"
    }
    column "breakdown_by" {
      type = "Array(String)"
    }
    column "entity_math" {
      type = "Array(String)"
    }
    column "filter" {
      type = "String"
    }
    column "tables" {
      type = "Array(LowCardinality(String))"
    }
    column "columns" {
      type = "Array(LowCardinality(String))"
    }
    column "query" {
      type = "String"
    }
    column "log_comment" {
      type = "String"
    }
    column "is_exception" {
      type = "UInt8"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.metrics_query_log"
      replica_name = "{replica}-{shard}"
    }
  }

  table "new_raw_sessions" {
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
    column "initial__kx" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_raw_sessions"
      sharding_key    = "cityHash64(session_id_v7)"
    }
  }

  table "new_sessions" {
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

  table "new_writable_raw_sessions" {
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
    column "initial__kx" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_raw_sessions"
      sharding_key    = "cityHash64(session_id_v7)"
    }
  }

  table "new_writable_sessions" {
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

  table "pending_person_deletes_reporting" {
    order_by = ["team_id", "deletion_type", "key"]
    settings = {
      index_granularity = "8192"
    }
    column "id" {
      type = "UInt64"
    }
    column "deletion_type" {
      type = "UInt8"
    }
    column "key" {
      type = "String"
    }
    column "group_type_index" {
      type = "Nullable(String)"
    }
    column "created_at" {
      type = "DateTime"
    }
    column "delete_verified_at" {
      type = "Nullable(DateTime)"
    }
    column "created_by_id" {
      type = "Nullable(String)"
    }
    column "team_id" {
      type = "Int64"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/pending_person_deletes_reporting"
      replica_name = "{shard}-{replica}"
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
      type    = "Int8"
      default = "0"
    }
    column "version" {
      type = "UInt64"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "last_seen_at" {
      type = "Nullable(DateTime64(3))"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.person"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  table "person_collapsing" {
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
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_sign" {
      type = "Int8"
    }
    engine "replicated_collapsing_merge_tree" {
      zoo_path     = "/clickhouse/prod/tables/noshard/posthog.person_collapsing"
      replica_name = "{replica}-{shard}"
      sign_column  = "_sign"
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
      type    = "Int64"
      default = "1"
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

  table "person_overrides_to_delete" {
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "partitions" {
      type = "Array(String)"
    }
    engine "join" {
      strictness = "ANY"
      type       = "LEFT"
      keys       = ["team_id", "distinct_id"]
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
      zoo_path       = "/clickhouse/tables/noshard/posthog.plugin_log_entries.fixed"
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
      materialized = "bitShiftLeft(toUInt64(NOT (property_type IS NULL)), 48) + toUInt64(toUnixTimestamp(last_seen_at))"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.property_definitions"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
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
      cluster_name    = "sessions"
      remote_database = "posthog"
      remote_table    = "raw_sessions"
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
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "has_replay_events" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    engine "distributed" {
      cluster_name    = "sessions"
      remote_database = "posthog"
      remote_table    = "raw_sessions_v3"
      sharding_key    = "cityHash64(session_id_v7)"
    }
  }

  table "session_recording_events" {
    column "uuid" {
      type = "UUID"
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
    column "session_id" {
      type = "String"
    }
    column "window_id" {
      type = "String"
    }
    column "snapshot_data" {
      type = "String"
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
    column "has_full_snapshot" {
      type    = "Int8"
      comment = "column_materializer::has_full_snapshot"
    }
    column "events_summary" {
      type    = "Array(String)"
      comment = "column_materializer::events_summary"
    }
    column "click_count" {
      type    = "Int8"
      comment = "column_materializer::click_count"
    }
    column "keypress_count" {
      type    = "Int8"
      comment = "column_materializer::keypress_count"
    }
    column "timestamps_summary" {
      type    = "Array(DateTime64(6, 'UTC'))"
      comment = "column_materializer::timestamps_summary"
    }
    column "first_event_timestamp" {
      type    = "DateTime64(6, 'UTC')"
      comment = "column_materializer::first_event_timestamp"
    }
    column "last_event_timestamp" {
      type    = "DateTime64(6, 'UTC')"
      comment = "column_materializer::last_event_timestamp"
    }
    column "urls" {
      type    = "Array(String)"
      comment = "column_materializer::urls"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_session_recording_events"
      sharding_key    = "sipHash64(distinct_id)"
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
      cluster_name    = "sessions"
      remote_database = "posthog"
      remote_table    = "sessions"
      sharding_key    = "sipHash64(session_id)"
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

  table "sharded_events" {
    order_by     = ["team_id", "toDate(timestamp)", "event", "cityHash64(distinct_id)", "cityHash64(uuid)"]
    partition_by = "toYYYYMM(timestamp)"
    sample_by    = "cityHash64(distinct_id)"
    settings = {
      index_granularity                    = "8192"
      max_avg_part_size_for_too_many_parts = "0"
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
    column "$group_0" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), '^\"|\"$', '')"
      comment = "column_materializer::$group_0"
    }
    column "$group_1" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_1'), '^\"|\"$', '')"
      comment = "column_materializer::$group_1"
    }
    column "$group_2" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_2'), '^\"|\"$', '')"
      comment = "column_materializer::$group_2"
    }
    column "$group_3" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_3'), '^\"|\"$', '')"
      comment = "column_materializer::$group_3"
    }
    column "$group_4" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_4'), '^\"|\"$', '')"
      comment = "column_materializer::$group_4"
    }
    column "$window_id" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$window_id'), '^\"|\"$', '')"
      comment = "column_materializer::$window_id"
    }
    column "$session_id" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$session_id'), '^\"|\"$', '')"
      comment = "column_materializer::$session_id"
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
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "mat_metadata_backend" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, 'metadata.backend'), '^\"|\"$', '')"
    }
    column "mat_metadata_loggedIn" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, 'metadata.loggedIn'), '^\"|\"$', '')"
    }
    column "elements_chain_href" {
      type         = "String"
      materialized = "EXTRACT(elements_chain, '(?::|\")href=\"(.*?)\"')"
    }
    column "elements_chain_texts" {
      type         = "Array(String)"
      materialized = "arrayDistinct(extractAll(elements_chain, '(?::|\")text=\"(.*?)\"'))"
    }
    column "elements_chain_ids" {
      type         = "Array(String)"
      materialized = "arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id=\"(.*?)\"'))"
    }
    column "elements_chain_elements" {
      type         = "Array(Enum8('a'=1, 'button'=2, 'form'=3, 'input'=4, 'select'=5, 'textarea'=6, 'label'=7))"
      materialized = "arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\\\.|$|:)'))"
    }
    column "properties_group_custom" {
      type         = "Map(String, String)"
      materialized = "mapSort(mapFilter((key, _) -> ((key NOT LIKE '$%') AND (key NOT IN ('token', 'distinct_id', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'gad_source', 'gclsrc', 'dclid', 'gbraid', 'wbraid', 'fbclid', 'msclkid', 'twclid', 'li_fat_id', 'mc_cid', 'igshid', 'ttclid', 'rdt_cid'))), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))"
      codec        = "ZSTD(1)"
    }
    column "properties_group_feature_flags" {
      type         = "Map(String, String)"
      materialized = "mapSort(mapFilter((key, _) -> (key LIKE '$feature/%'), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))"
      codec        = "ZSTD(1)"
    }
    column "is_deleted" {
      type = "Bool"
    }
    column "person_properties_map_custom" {
      type         = "Map(String, String)"
      materialized = "mapSort(mapFilter((key, _) -> (key NOT LIKE '$%'), CAST(JSONExtractKeysAndValues(person_properties, 'String'), 'Map(String, String)')))"
      codec        = "ZSTD(1)"
    }
    column "mat_$ai_trace_id" {
      type    = "Nullable(String)"
      default = "JSONExtract(properties, '$ai_trace_id', 'Nullable(String)')"
    }
    column "$session_id_uuid" {
      type         = "Nullable(UInt128)"
      materialized = "toUInt128(JSONExtract(properties, '$session_id', 'Nullable(UUID)'))"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
    column "properties_group_ai" {
      type         = "Map(String, String)"
      materialized = "mapSort(mapFilter((key, _) -> ((key LIKE '$ai_%') AND (key NOT IN ('$ai_input', '$ai_input_state', '$ai_output', '$ai_output_choices', '$ai_output_state', '$ai_tools'))), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))"
      codec        = "ZSTD(1)"
    }
    column "mat_historical_migration" {
      type    = "Nullable(String)"
      default = "JSONExtract(properties, 'historical_migration', 'Nullable(String)')"
    }
    column "mat_$ai_session_id" {
      type         = "Nullable(String)"
      materialized = "JSONExtract(properties, '$ai_session_id', 'Nullable(String)')"
    }
    column "mat_$ai_is_error" {
      type         = "Nullable(String)"
      materialized = "JSONExtract(properties, '$ai_is_error', 'Nullable(String)')"
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
    column "historical_migration" {
      type = "Bool"
    }
    column "mat_$ai_prompt_name" {
      type         = "Nullable(String)"
      materialized = "JSONExtract(properties, '$ai_prompt_name', 'Nullable(String)')"
    }
    column "properties_map_ephemeral" {
      type = "Map(String, String)"
    }
    column "person_properties_map_ephemeral" {
      type = "Map(String, String)"
    }
    column "mat_$ai_experiment_id" {
      type    = "Nullable(String)"
      default = "JSONExtract(properties, '$ai_experiment_id', 'Nullable(String)')"
    }
    index "minmax_inserted_at" {
      expr        = "coalesce(inserted_at, _timestamp)"
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
    index "is_deleted_idx" {
      expr        = "is_deleted"
      type        = "minmax"
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
    index "bloom_filter_$ai_trace_id" {
      expr        = "`mat_$ai_trace_id`"
      type        = "bloom_filter(0.001)"
      granularity = 2
    }
    index "minmax_mat_historical_migration" {
      expr        = "mat_historical_migration"
      type        = "minmax"
      granularity = 1
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
    index "minmax_$session_id_uuid" {
      expr        = "`$session_id_uuid`"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_filter_$session_id" {
      expr        = "nullIf(nullIf(`$session_id`, ''), 'null')"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_mat_metadata_backend" {
      expr        = "mat_metadata_backend"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_metadata_loggedIn" {
      expr        = "mat_metadata_loggedIn"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_mat_$ai_trace_id" {
      expr        = "`mat_$ai_trace_id`"
      type        = "minmax"
      granularity = 1
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.events"
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

  table "sharded_flag_evaluations" {
    order_by     = ["team_id", "flag_key", "toDate(timestamp)", "cityHash64(distinct_id)"]
    partition_by = "toYYYYMM(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalDay(90)"
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
    column "inserted_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "timestamp"
    }
    column "$group_0" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), '^\"|\"$', '')"
      comment = "column_materializer::$group_0"
    }
    column "$group_1" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_1'), '^\"|\"$', '')"
      comment = "column_materializer::$group_1"
    }
    column "$group_2" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_2'), '^\"|\"$', '')"
      comment = "column_materializer::$group_2"
    }
    column "$group_3" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_3'), '^\"|\"$', '')"
      comment = "column_materializer::$group_3"
    }
    column "$group_4" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_4'), '^\"|\"$', '')"
      comment = "column_materializer::$group_4"
    }
    column "flag_key" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag'), '^\"|\"$', '')"
      comment = "column_materializer::properties::$feature_flag"
    }
    column "response" {
      type    = "LowCardinality(String)"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag_response'), '^\"|\"$', '')"
      comment = "column_materializer::properties::$feature_flag_response"
    }
    column "session_id" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$session_id'), '^\"|\"$', '')"
      comment = "column_materializer::properties::$session_id"
    }
    column "request_id" {
      type    = "String"
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag_request_id'), '^\"|\"$', '')"
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

  table "sharded_raw_sessions_v3" {
    order_by     = ["team_id", "session_timestamp", "session_id_v7"]
    partition_by = "toYYYYMM(session_timestamp)"
    settings = {
      index_granularity = "8192"
    }
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
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
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
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.raw_sessions_v3"
      replica_name = "{replica}"
    }
  }

  table "sharded_session_recording_events" {
    order_by     = ["team_id", "toHour(timestamp)", "session_id", "timestamp", "uuid"]
    partition_by = "toYYYYMMDD(timestamp)"
    ttl          = "toDate(created_at) + toIntervalWeek(3)"
    settings = {
      index_granularity = "512"
    }
    column "uuid" {
      type = "UUID"
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
    column "session_id" {
      type = "String"
    }
    column "window_id" {
      type = "String"
    }
    column "snapshot_data" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "has_full_snapshot" {
      type         = "Int8"
      materialized = "JSONExtractBool(snapshot_data, 'has_full_snapshot')"
      comment      = "column_materializer::has_full_snapshot"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "events_summary" {
      type         = "Array(String)"
      materialized = "JSONExtract(JSON_QUERY(snapshot_data, '$.events_summary[*]'), 'Array(String)')"
    }
    column "click_count" {
      type         = "Int8"
      materialized = "length(arrayFilter(x -> ((JSONExtractInt(x, 'type') = 3) AND (JSONExtractInt(x, 'data', 'source') = 2) AND (JSONExtractInt(x, 'data', 'source') = 2)), events_summary))"
    }
    column "keypress_count" {
      type         = "Int8"
      materialized = "length(arrayFilter(x -> ((JSONExtractInt(x, 'type') = 3) AND (JSONExtractInt(x, 'data', 'source') = 5)), events_summary))"
    }
    column "timestamps_summary" {
      type         = "Array(DateTime64(6, 'UTC'))"
      materialized = "arraySort(arrayMap(x -> toDateTime(JSONExtractInt(x, 'timestamp') / 1000), events_summary))"
    }
    column "first_event_timestamp" {
      type         = "DateTime64(6, 'UTC')"
      materialized = "arrayReduce('min', timestamps_summary)"
    }
    column "last_event_timestamp" {
      type         = "DateTime64(6, 'UTC')"
      materialized = "arrayReduce('max', timestamps_summary)"
    }
    column "urls" {
      type         = "Array(String)"
      materialized = "arrayFilter(x -> (x != ''), arrayMap(x -> JSONExtractString(x, 'data', 'href'), events_summary))"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.session_recording_events"
      replica_name   = "{replica}"
      version_column = "_timestamp"
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
      index_granularity   = "512"
      ttl_only_drop_parts = "1"
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
      type = "AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))"
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

  table "swap_person_distinct_id" {
    order_by = ["team_id", "distinct_id", "person_id"]
    settings = {
      index_granularity = "8192"
    }
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
      zoo_path     = "/clickhouse/prod/tables/noshard/posthog.swap_person_distinct_id"
      replica_name = "{replica}-{shard}"
      sign_column  = "_sign"
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
      cluster_name    = "ops"
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

  table "web_bounces_daily_distributed" {
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
    column "updated_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "web_bounces_daily"
      sharding_key    = "rand()"
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

  table "web_bounces_hourly_distributed" {
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
    column "updated_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "web_bounces_hourly"
      sharding_key    = "rand()"
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
    order_by     = ["team_id", "period_bucket", "host", "device_type", "entry_pathname", "end_pathname", "browser", "os", "viewport_width", "viewport_height", "referring_domain", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "country_code", "city_name", "region_code", "region_name", "has_gclid", "has_gad_source_paid_search", "has_fbclid"]
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
    column "mat_metadata_backend" {
      type = "Nullable(String)"
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
    column "mat_metadata_loggedIn" {
      type = "Nullable(Bool)"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.web_pre_aggregated_bounces"
      replica_name = "{replica}-{shard}"
    }
  }

  table "web_pre_aggregated_stats" {
    order_by     = ["team_id", "period_bucket", "host", "device_type", "pathname", "entry_pathname", "end_pathname", "browser", "os", "viewport_width", "viewport_height", "referring_domain", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "country_code", "city_name", "region_code", "region_name", "has_gclid", "has_gad_source_paid_search", "has_fbclid"]
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
    column "mat_metadata_backend" {
      type = "Nullable(String)"
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
    column "mat_metadata_loggedIn" {
      type = "Nullable(Bool)"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.web_pre_aggregated_stats"
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

  table "web_stats_daily_distributed" {
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
    column "updated_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
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
    column "persons_uniq_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sessions_uniq_state" {
      type = "AggregateFunction(uniq, String)"
    }
    column "pageviews_count_state" {
      type = "AggregateFunction(sum, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "web_stats_daily"
      sharding_key    = "rand()"
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

  table "web_stats_hourly_distributed" {
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
    column "updated_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
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
    column "persons_uniq_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sessions_uniq_state" {
      type = "AggregateFunction(uniq, String)"
    }
    column "pageviews_count_state" {
      type = "AggregateFunction(sum, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "web_stats_hourly"
      sharding_key    = "rand()"
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
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
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
    column "inserted_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    engine "distributed" {
      cluster_name    = "batch_exports_writable"
      remote_database = "posthog"
      remote_table    = "sharded_events_recent"
      sharding_key    = "sipHash64(distinct_id)"
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
    column "initial__kx" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    engine "distributed" {
      cluster_name    = "sessions"
      remote_database = "posthog"
      remote_table    = "raw_sessions"
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
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
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
      cluster_name    = "sessions"
      remote_database = "posthog"
      remote_table    = "raw_sessions_v3"
      sharding_key    = "cityHash64(session_id_v7)"
    }
  }

  table "writable_session_recording_events" {
    column "uuid" {
      type = "UUID"
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
    column "session_id" {
      type = "String"
    }
    column "window_id" {
      type = "String"
    }
    column "snapshot_data" {
      type = "String"
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_session_recording_events"
      sharding_key    = "sipHash64(distinct_id)"
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
      cluster_name    = "sessions"
      remote_database = "posthog"
      remote_table    = "sessions"
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
  sum(click_count) AS click_count,
  sum(keypress_count) AS keypress_count,
  sum(mouse_activity_count) AS mouse_activity_count,
  sum(rage_click_count) AS rage_click_count,
  sum(dead_click_count) AS dead_click_count,
  sum(inter_action_gap_count) AS inter_action_gap_count,
  sum(inter_action_gap_sum_ms) AS inter_action_gap_sum_ms,
  sum(inter_action_gap_sum_of_squares_ms) AS inter_action_gap_sum_of_squares_ms,
  max(max_idle_gap_ms) AS max_idle_gap_ms,
  sum(quick_back_count) AS quick_back_count,
  sum(page_visit_count) AS page_visit_count,
  uniqExactArrayState(visited_urls) AS unique_url_count,
  sum(console_error_count) AS console_error_count,
  sum(console_error_after_click_count) AS console_error_after_click_count,
  sum(network_request_count) AS network_request_count,
  sum(network_failed_request_count) AS network_failed_request_count,
  sum(network_request_duration_sum) AS network_request_duration_sum,
  sum(network_request_duration_sum_of_squares) AS network_request_duration_sum_of_squares,
  sum(network_request_duration_count) AS network_request_duration_count,
  max(max_scroll_y) AS max_scroll_y,
  uniqExactArrayState(click_target_ids) AS unique_click_target_count,
  sum(text_selection_count) AS text_selection_count,
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
    column "quick_back_count" {
      type = "Int64"
    }
    column "page_visit_count" {
      type = "Int64"
    }
    column "unique_url_count" {
      type = "AggregateFunction(uniqExactArray, Array(String))"
    }
    column "console_error_count" {
      type = "Int64"
    }
    column "console_error_after_click_count" {
      type = "Int64"
    }
    column "network_request_count" {
      type = "Int64"
    }
    column "network_failed_request_count" {
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
    column "max_scroll_y" {
      type = "Float64"
    }
    column "unique_click_target_count" {
      type = "AggregateFunction(uniqExactArray, Array(Int64))"
    }
    column "text_selection_count" {
      type = "Int64"
    }
    column "is_deleted" {
      type = "UInt8"
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
FROM posthog.custom_metrics_server_crash
UNION ALL
SELECT *
FROM posthog.custom_metrics_table_sizes
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_part_counts
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_dictionaries
UNION ALL
SELECT
  'ClickHouseCustomMetric_S3DiskBytesUsed' AS name,
  map('instance', hostname(), 'disk', disk_name) AS labels,
  toFloat64(sum(bytes_on_disk)) AS value,
  'Bytes currently used by ClickHouse parts on S3-backed disks on this node' AS help,
  'gauge' AS type
FROM system.parts
WHERE disk_name IN ('s3disk', 'cache')
GROUP BY
  disk_name
UNION ALL
SELECT
  'ClickHouseCustomMetric_MergeFailures15m' AS name,
  map('instance', hostname()) AS labels,
  toFloat64(count()) AS value,
  'Number of failed merge operations in the last 15 minutes' AS help,
  'gauge' AS type
FROM system.part_log
WHERE
  (event_time >= (now() - toIntervalMinute(15)))
AND
  (event_type = 'MergeParts')
AND
  (error > 0)
AND
  (merge_reason != 'NotAMerge')
AND
  (error != 40)
UNION ALL
SELECT
  'ClickHouseCustomMetric_MergeRetriesMaxPerTable15m' AS name,
  map('instance', hostname()) AS labels,
  toFloat64(max(cnt)) AS value,
  'Max failed merge retries for any single table in the last 15 minutes' AS help,
  'gauge' AS type
FROM
  (
    SELECT count() AS cnt
    FROM system.part_log
    WHERE
      (event_time >= (now() - toIntervalMinute(15)))
    AND
      (event_type = 'MergeParts')
    AND
      (error > 0)
    AND
      (merge_reason != 'NotAMerge')
    AND
      (error != 40)
    GROUP BY
      database, `table`, partition_id
  )
SQL

  }

  view "custom_metrics_backups" {
    query = <<SQL
WITH
  ['ClickHouseCustomMetric_BackupFailed', 'ClickHouseCustomMetric_BackupSuccess', 'ClickHouseCustomMetric_BackupCancelled', 'ClickHouseCustomMetric_BackupAttempts'] AS names,
  [toInt64(countIf(status = 'BACKUP_FAILED')), toInt64(countIf(status = 'BACKUP_CREATED')), toInt64(countIf(status = 'BACKUP_CANCELLED')), toInt64(countIf(status = 'CREATING_BACKUP'))] AS `values`,
  ['Number of failed backups', 'Number of successful backups', 'Number of cancelled backups', 'Number of backup attempts'] AS descriptions,
  ['gauge', 'gauge', 'gauge', 'gauge'] AS types,
  arrayJoin(arrayZip(names, `values`, descriptions, types)) AS tpl
SELECT
  tpl.1 AS name,
  map('instance', hostname()) AS labels,
  tpl.2 AS value,
  tpl.3 AS help,
  tpl.4 AS type
FROM system.backup_log
WHERE event_date = today()
GROUP BY
  event_date
SQL

  }

  view "custom_metrics_dictionaries" {
    query = <<SQL
SELECT
  'ClickHouseCustomMetric_DictionariesFailed' AS name,
  map(
    'instance',
    hostname(),
    'database',
    d.database,
    'dictionary',
    d.dict_name,
    'uuid',
    toString(d.uuid),
    'status',
    toString(d.status)
  ) AS labels,
  toUInt64(1) AS value,
  'Dictionary is in FAILED or FAILED_AND_RELOADING status' AS help,
  'gauge' AS type
FROM
  (
    SELECT name AS dict_name, database, uuid, status
    FROM system.dictionaries
    WHERE status IN ('FAILED', 'FAILED_AND_RELOADING')
  ) AS d
SQL

  }

  view "custom_metrics_part_counts" {
    query = <<SQL
SELECT
  'ClickHouseCustomMetric_MaxPartCountPerPartition' AS name,
  map('instance', hostname(), 'database', database, 'table', `table`, 'partition', partition) AS labels,
  part_count AS value,
  'Maximum number of active parts for any partition in a PostHog table' AS help,
  'gauge' AS type
FROM
  (
    SELECT database, `table`, partition, count() AS part_count
    FROM system.parts
    WHERE
      active
    AND
      (database = 'posthog')
    GROUP BY
      database, `table`, partition
    ORDER BY database ASC, `table` ASC, part_count DESC, partition ASC
    LIMIT 1 BY database, `table`
  )
SQL

  }

  view "custom_metrics_replication_queue" {
    query = <<SQL
WITH
  ['ClickHouseCustomMetric_ReplicationQueueStuckEntries', 'ClickHouseCustomMetric_ReplicationQueueMaxPostponedEntrySeconds', 'ClickHouseCustomMetric_ReplicationQueueMaxErrorEntrySeconds'] AS names,
  [toInt64(countIf(create_time < (now() - toIntervalDay(15)))), maxIf(dateDiff('seconds', create_time, last_postpone_time), last_postpone_time != '1970-01-01'), maxIf(dateDiff('seconds', create_time, last_exception_time), (last_exception_time != '1970-01-01') AND (last_exception_time > (now() - toIntervalMinute(5))))] AS `values`,
  ['Number of entries that have been in the replication queue for more than 15 days', 'Maximum number of seconds that an entry has been postponed', 'Maximum number of seconds that an entry has been in error'] AS descriptions,
  ['gauge', 'gauge', 'gauge'] AS types,
  arrayJoin(arrayZip(names, `values`, descriptions, types)) AS tpl
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
  argMaxMerge(person_id) AS person_id,
  groupUniqArrayMerge(distinct_ids) AS distinct_ids,
  min(min_timestamp) AS min_timestamp,
  max(max_timestamp) AS max_timestamp,
  max(max_inserted_at) AS max_inserted_at,
  arrayDistinct(arrayFlatten(groupArray(urls))) AS urls,
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
  uniqUpToMerge(1)(page_screen_autocapture_uniq_up_to) AS page_screen_autocapture_uniq_up_to,
  groupUniqArrayMapMerge(flag_values) AS flag_values
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
      user  = "dict_reader"
      table = "channel_definition"
    }
    layout "complex_key_hashed" {
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
      user  = "dict_reader"
      query = "SELECT     team_id FROM     `web_pre_aggregated_teams` FINAL WHERE version > 0"
    }
    layout "hashed" {
    }
  }
}

named_collection "msk_cluster" {
  external = true
}

named_collection "warpstream_calculated_events" {
  external = true
}

named_collection "warpstream_cyclotron" {
  external = true
}

named_collection "warpstream_ingestion" {
  external = true
}

named_collection "warpstream_logs" {
  external = true
}

named_collection "warpstream_metrics" {
  external = true
}

named_collection "warpstream_replay" {
  external = true
}

named_collection "warpstream_shared" {
  external = true
}

named_collection "warpstream_traces" {
  external = true
}
