database "posthog" {
  table "ingestion_warnings_v2" {
    order_by     = ["team_id", "type", "timestamp"]
    partition_by = "toYYYYMM(timestamp)"
    ttl          = "toDateTime(timestamp) + toIntervalDay(90)"
    settings = {
      index_granularity = "8192"
    }
    extend = "_ingestion_warnings_v2_columns"
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.ingestion_warnings_v2"
      replica_name = "{replica}-{shard}"
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
  table "sharded_conversion_goal_attributed_preaggregated" {
    order_by     = ["team_id", "job_id", "person_id", "conversion_timestamp", "touchpoint_timestamp"]
    partition_by = "toYYYYMMDD(expires_at)"
    ttl          = "expires_at"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    extend = "_conversion_goal_attributed_preaggregated_columns"
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.conversion_goal_attributed_preaggregated"
      replica_name   = "{replica}-{shard}"
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
    extend = "_experiment_metric_events_preaggregated_columns"
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.experiment_metric_events_preaggregated"
      replica_name   = "{replica}-{shard}"
      version_column = "computed_at"
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
    extend = "_marketing_conversions_preaggregated_columns"
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
    extend = "_marketing_costs_preaggregated_columns"
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
    extend = "_marketing_touchpoints_preaggregated_columns"
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.marketing_touchpoints_preaggregated"
      replica_name   = "{replica}-{shard}"
      version_column = "computed_at"
    }
  }
  table "sharded_session_replay_features" {
    order_by     = ["team_id", "session_id"]
    partition_by = "toYYYYMM(min_first_timestamp)"
    settings = {
      index_granularity = "512"
    }
    extend = "_session_replay_features_columns"
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.session_replay_features"
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
    extend = "_web_bot_definition_columns"
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
    extend = "_web_bounces_dimensional_preaggregated_columns"
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
    extend = "_web_goals_preaggregated_columns"
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
    extend = "_web_stats_dimensional_preaggregated_columns"
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
    extend = "_web_stats_frustration_preaggregated_columns"
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
    extend = "_web_stats_preaggregated_columns"
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
    extend = "_web_vitals_paths_preaggregated_columns"
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.web_vitals_paths_preaggregated"
      replica_name   = "{replica}"
      version_column = "computed_at"
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
  materialized_view "hog_invocation_results_mv" {
    to_table = "posthog.hog_invocation_results_data"
    query    = file("sql/hog_invocation_results_mv.sql")

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
  materialized_view "ingestion_warnings_v2_mv" {
    to_table = "posthog.ingestion_warnings_v2"
    query    = file("sql/ingestion_warnings_v2_mv.sql")

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
  materialized_view "message_assets_mv" {
    to_table = "posthog.message_assets_data"
    query    = file("sql/message_assets_mv.sql")

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
  materialized_view "property_values_mv" {
    to_table = "posthog.property_values"
    query    = file("sql/property_values_mv.sql")

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
}
