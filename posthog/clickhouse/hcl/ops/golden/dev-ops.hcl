node "dev-us-iad-ch-1a-ops" {
  macros = {
    hostClusterRole = "ops"
    hostClusterType = "offline"
    replica         = "a"
    shard           = "1"
  }
}

database "posthog" {
  table "events_team_daily_stats" {
    order_by = ["analysis_date", "team_id", "event"]
    settings = {
      index_granularity = "8192"
    }
    column "analysis_date" {
      type = "Date"
    }
    column "team_id" {
      type = "Int64"
    }
    column "event" {
      type = "String"
    }
    column "event_count" {
      type = "UInt64"
    }
    column "total_event_bytes" {
      type = "UInt64"
    }
    column "min_event_bytes" {
      type = "UInt64"
    }
    column "max_event_bytes" {
      type = "UInt64"
    }
    column "avg_event_bytes" {
      type = "Float64"
    }
    column "p50_event_bytes" {
      type = "Float64"
    }
    column "p90_event_bytes" {
      type = "Float64"
    }
    column "p95_event_bytes" {
      type = "Float64"
    }
    column "p99_event_bytes" {
      type = "Float64"
    }
    column "event_size_histogram" {
      type = "Array(Tuple(Float64, Float64, UInt64))"
    }
    column "computed_at" {
      type = "DateTime"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/ops/tables/{shard}/posthog.events_team_daily_stats"
      replica_name = "{replica}"
    }
  }

  table "prom_metrics" {
    column "id" {
      type = "UUID"
    }
    column "timestamp" {
      type = "DateTime64(3)"
    }
    column "value" {
      type = "Float64"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "tags" {
      type = "Map(LowCardinality(String), String)"
    }
    column "all_tags" {
      type = "Map(String, String)"
    }
    column "min_time" {
      type = "Nullable(DateTime64(3))"
    }
    column "max_time" {
      type = "Nullable(DateTime64(3))"
    }
    column "metric_family_name" {
      type = "String"
    }
    column "type" {
      type = "String"
    }
    column "unit" {
      type = "String"
    }
    column "help" {
      type = "String"
    }
    engine "time_series" {
      samples {
        target = "posthog.prom_metrics_data"
      }
      tags {
        target = "posthog.prom_metrics_tags"
      }
      metrics {
        target = "posthog.prom_metrics_metrics"
      }
    }
  }

  table "prom_metrics_data" {
    order_by = ["id", "timestamp"]
    settings = {
      index_granularity = "8192"
    }
    column "id" {
      type = "UUID"
    }
    column "timestamp" {
      type = "DateTime64(3)"
    }
    column "value" {
      type = "Float64"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/ops/tables/{shard}/posthog.prom_metrics/data"
      replica_name = "{replica}"
    }
  }

  table "prom_metrics_metrics" {
    order_by = ["metric_family_name"]
    settings = {
      index_granularity = "8192"
    }
    column "metric_family_name" {
      type = "String"
    }
    column "type" {
      type = "String"
    }
    column "unit" {
      type = "String"
    }
    column "help" {
      type = "String"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path     = "/clickhouse/ops/tables/{shard}/posthog.prom_metrics/metrics"
      replica_name = "{replica}"
    }
  }

  table "prom_metrics_tags" {
    order_by = ["metric_name", "id"]
    settings = {
      index_granularity = "8192"
    }
    column "id" {
      type = "UUID"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "tags" {
      type = "Map(LowCardinality(String), String)"
    }
    column "all_tags" {
      type = "Map(String, String)"
    }
    column "min_time" {
      type = "SimpleAggregateFunction(min, Nullable(DateTime64(3)))"
    }
    column "max_time" {
      type = "SimpleAggregateFunction(max, Nullable(DateTime64(3)))"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/ops/tables/{shard}/posthog.prom_metrics/tags"
      replica_name = "{replica}"
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
      cluster_name    = "ops"
      remote_database = "posthog"
      remote_table    = "sharded_query_log_archive"
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
      zoo_path     = "/clickhouse/tables/noshard/posthog.sharded_query_log_archive"
      replica_name = "{replica}-{shard}"
    }
  }

  table "writable_prom_metrics" {
    column "id" {
      type = "UUID"
    }
    column "timestamp" {
      type = "DateTime64(3)"
    }
    column "value" {
      type = "Float64"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "tags" {
      type = "Map(LowCardinality(String), String)"
    }
    column "all_tags" {
      type = "Map(String, String)"
    }
    column "min_time" {
      type = "Nullable(DateTime64(3))"
    }
    column "max_time" {
      type = "Nullable(DateTime64(3))"
    }
    column "metric_family_name" {
      type = "String"
    }
    column "type" {
      type = "String"
    }
    column "unit" {
      type = "String"
    }
    column "help" {
      type = "String"
    }
    engine "time_series" {
      samples {
        target = "posthog.writable_prom_metrics_data"
      }
      tags {
        target = "posthog.writable_prom_metrics_tags"
      }
      metrics {
        target = "posthog.writable_prom_metrics_metrics"
      }
    }
  }

  table "writable_prom_metrics_data" {
    column "id" {
      type = "UUID"
    }
    column "timestamp" {
      type = "DateTime64(3)"
    }
    column "value" {
      type = "Float64"
    }
    engine "buffer" {
      database   = "posthog"
      table      = "prom_metrics_data"
      num_layers = 1
      min_time   = 2
      max_time   = 5
      min_rows   = 1
      max_rows   = 1000000
      min_bytes  = 1
      max_bytes  = 100000000
    }
  }

  table "writable_prom_metrics_metrics" {
    column "metric_family_name" {
      type = "String"
    }
    column "type" {
      type = "String"
    }
    column "unit" {
      type = "String"
    }
    column "help" {
      type = "String"
    }
    engine "buffer" {
      database   = "posthog"
      table      = "prom_metrics_metrics"
      num_layers = 1
      min_time   = 2
      max_time   = 5
      min_rows   = 1
      max_rows   = 1000000
      min_bytes  = 1
      max_bytes  = 100000000
    }
  }

  table "writable_prom_metrics_tags" {
    column "id" {
      type = "UUID"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "tags" {
      type = "Map(LowCardinality(String), String)"
    }
    column "all_tags" {
      type = "Map(String, String)"
    }
    column "min_time" {
      type = "SimpleAggregateFunction(min, Nullable(DateTime64(3)))"
    }
    column "max_time" {
      type = "SimpleAggregateFunction(max, Nullable(DateTime64(3)))"
    }
    engine "buffer" {
      database   = "posthog"
      table      = "prom_metrics_tags"
      num_layers = 1
      min_time   = 2
      max_time   = 5
      min_rows   = 1
      max_rows   = 1000000
      min_bytes  = 1
      max_bytes  = 100000000
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
      remote_table    = "sharded_query_log_archive"
    }
  }

  materialized_view "ops_query_log_archive_mv" {
    to_table = "posthog.writable_query_log_archive"
    query    = "SELECT hostname, user, query_id, initial_query_id, is_initial_query, type, event_date, event_time, event_time_microseconds, query_start_time, query_start_time_microseconds, query_duration_ms, read_rows, read_bytes, written_rows, written_bytes, result_rows, result_bytes, memory_usage, peak_threads_usage, current_database, query, formatted_query, normalized_query_hash, query_kind, exception_code, exception, stack_trace, JSONExtractInt(log_comment, 'team_id') AS team_id, if(isValidJSON(log_comment), log_comment, '{}') AS log_comment, ProfileEvents FROM system.query_log WHERE type != 'QueryStart'"
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

  view "custom_metrics" {
    query          = "SELECT * REPLACE(toFloat64(value) AS value) FROM posthog.custom_metrics_test UNION ALL SELECT * REPLACE(toFloat64(value) AS value) FROM posthog.custom_metrics_replication_queue UNION ALL SELECT * REPLACE(toFloat64(value) AS value) FROM posthog.custom_metrics_server_crash UNION ALL SELECT * FROM posthog.custom_metrics_table_sizes UNION ALL SELECT * REPLACE(toFloat64(value) AS value) FROM posthog.custom_metrics_part_counts UNION ALL SELECT * REPLACE(toFloat64(value) AS value) FROM posthog.custom_metrics_dictionaries UNION ALL SELECT 'ClickHouseCustomMetric_S3DiskBytesUsed' AS name, map('instance', hostname(), 'disk', disk_name) AS labels, toFloat64(sum(bytes_on_disk)) AS value, 'Bytes currently used by ClickHouse parts on S3-backed disks on this node' AS help, 'gauge' AS type FROM system.parts WHERE disk_name IN ('s3disk', 'cache') GROUP BY disk_name UNION ALL SELECT 'ClickHouseCustomMetric_MergeFailures15m' AS name, map('instance', hostname()) AS labels, toFloat64(count()) AS value, 'Number of failed merge operations in the last 15 minutes' AS help, 'gauge' AS type FROM system.part_log WHERE (event_time >= (now() - toIntervalMinute(15))) AND (event_type = 'MergeParts') AND (error > 0) AND (merge_reason != 'NotAMerge') UNION ALL SELECT 'ClickHouseCustomMetric_MergeRetriesMaxPerTable15m' AS name, map('instance', hostname()) AS labels, toFloat64(max(cnt)) AS value, 'Max failed merge retries for any single table in the last 15 minutes' AS help, 'gauge' AS type FROM (SELECT count() AS cnt FROM system.part_log WHERE (event_time >= (now() - toIntervalMinute(15))) AND (event_type = 'MergeParts') AND (error > 0) AND (merge_reason != 'NotAMerge') GROUP BY database, `table`, partition_id)"
    column_aliases = ["name", "labels", "value", "help", "type"]
  }

  view "custom_metrics_backups" {
    query          = "WITH ['ClickHouseCustomMetric_BackupFailed', 'ClickHouseCustomMetric_BackupSuccess', 'ClickHouseCustomMetric_BackupCancelled', 'ClickHouseCustomMetric_BackupAttempts'] AS names, [toInt64(countIf(status = 'BACKUP_FAILED')), toInt64(countIf(status = 'BACKUP_CREATED')), toInt64(countIf(status = 'BACKUP_CANCELLED')), toInt64(countIf(status = 'CREATING_BACKUP'))] AS values, ['Number of failed backups', 'Number of successful backups', 'Number of cancelled backups', 'Number of backup attempts'] AS descriptions, ['gauge', 'gauge', 'gauge', 'gauge'] AS types, arrayJoin(arrayZip(names, values, descriptions, types)) AS tpl SELECT tpl.1 AS name, map('instance', hostname()) AS labels, tpl.2 AS value, tpl.3 AS help, tpl.4 AS type FROM system.backup_log WHERE event_date = today() GROUP BY event_date"
    column_aliases = ["name", "labels", "value", "help", "type"]
  }

  view "custom_metrics_dictionaries" {
    query          = "SELECT 'ClickHouseCustomMetric_DictionariesFailed' AS name, map('instance', hostname(), 'database', d.database, 'dictionary', d.dict_name, 'uuid', toString(d.uuid), 'status', toString(d.status)) AS labels, toUInt64(1) AS value, 'Dictionary is in FAILED or FAILED_AND_RELOADING status' AS help, 'gauge' AS type FROM (SELECT name AS dict_name, database, uuid, status FROM system.dictionaries WHERE status IN ('FAILED', 'FAILED_AND_RELOADING')) AS d"
    column_aliases = ["name", "labels", "value", "help", "type"]
  }

  view "custom_metrics_part_counts" {
    query          = "SELECT 'ClickHouseCustomMetric_MaxPartCountPerPartition' AS name, map('instance', hostname(), 'database', database, 'table', `table`, 'partition', partition) AS labels, part_count AS value, 'Maximum number of active parts for any partition in a PostHog table' AS help, 'gauge' AS type FROM (SELECT database, `table`, partition, count() AS part_count FROM system.parts WHERE active AND (database = 'posthog') GROUP BY database, `table`, partition ORDER BY database ASC, `table` ASC, part_count DESC, partition ASC LIMIT 1 BY database, `table`)"
    column_aliases = ["name", "labels", "value", "help", "type"]
  }

  view "custom_metrics_replication_queue" {
    query          = "WITH ['ClickHouseCustomMetric_ReplicationQueueStuckEntries', 'ClickHouseCustomMetric_ReplicationQueueMaxPostponedEntrySeconds', 'ClickHouseCustomMetric_ReplicationQueueMaxErrorEntrySeconds'] AS names, [toInt64(countIf(create_time < (now() - toIntervalDay(15)))), maxIf(dateDiff('seconds', create_time, last_postpone_time), last_postpone_time != '1970-01-01'), maxIf(dateDiff('seconds', create_time, last_exception_time), (last_exception_time != '1970-01-01') AND (last_exception_time > (now() - toIntervalMinute(5))))] AS values, ['Number of entries that have been in the replication queue for more than 15 days', 'Maximum number of seconds that an entry has been postponed', 'Maximum number of seconds that an entry has been in error'] AS descriptions, ['gauge', 'gauge', 'gauge'] AS types, arrayJoin(arrayZip(names, values, descriptions, types)) AS tpl SELECT tpl.1 AS name, map('table', `table`, 'instance', hostname()) AS labels, tpl.2 AS value, tpl.3 AS help, tpl.4 AS type FROM system.replication_queue GROUP BY `table` HAVING value > 0"
    column_aliases = ["name", "labels", "value", "help", "type"]
  }

  view "custom_metrics_server_crash" {
    query          = "SELECT 'ClickHouseCustomMetric_ServerCrash' AS name, map('instance', hostname()) AS labels, count() AS value, 'Number of server crashes for current date' AS help, 'gauge' AS type FROM system.crash_log WHERE event_date = today() GROUP BY hostname()"
    column_aliases = ["name", "labels", "value", "help", "type"]
  }

  view "custom_metrics_table_sizes" {
    query          = "SELECT 'ClickHouseCustomMetric_TableTotalBytes' AS name, map('instance', hostname(), 'database', database, 'table', `table`) AS labels, CAST(total_bytes, 'Float64') AS value, 'Size of a database table on a given node (need a sum for sharded)' AS help, 'gauge' AS type FROM system.tables WHERE (database NOT IN ('INFORMATION_SCHEMA', 'information_schema')) AND (total_bytes IS NOT NULL)"
    column_aliases = ["name", "labels", "value", "help", "type"]
  }

  view "custom_metrics_test" {
    query          = "SELECT 'ClickHouseCustomMetric_Test' AS name, map('instance', hostname()) AS labels, 1 AS value, 'Test to check that the metric endpoint is working' AS help, 'gauge' AS type"
    column_aliases = ["name", "labels", "value", "help", "type"]
  }

  view "daily_aggregated_query_log_archive" {
    query          = "SELECT event_date AS day, team_id, user, current_database, query_kind, lc_kind, lc_access_method, lc_query_type, lc_product, lc_name, lc_feature, lc_query__kind, lc_api_key_label, count() AS query_count, sum(read_bytes) AS read_bytes, sum(read_rows) AS read_rows, sum(query_duration_ms) AS query_duration_ms, sum(ProfileEvents_OSCPUVirtualTimeMicroseconds) AS cpu_microseconds, countIf(exception_code != 0) AS error_count, countIf(exception_code IN (159, 160, 241)) AS timeout_oom_count FROM posthog.sharded_query_log_archive WHERE is_initial_query AND (event_date < today()) GROUP BY day, team_id, user, current_database, query_kind, lc_kind, lc_access_method, lc_query_type, lc_product, lc_name, lc_feature, lc_query__kind, lc_api_key_label"
    column_aliases = ["day", "team_id", "user", "current_database", "query_kind", "lc_kind", "lc_access_method", "lc_query_type", "lc_product", "lc_name", "lc_feature", "lc_query__kind", "lc_api_key_label", "query_count", "read_bytes", "read_rows", "query_duration_ms", "cpu_microseconds", "error_count", "timeout_oom_count"]
  }
}
