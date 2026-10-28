database "posthog" {
  table "event_property_daily_stats" {
    order_by = ["analysis_date", "team_id", "property_key"]
    ttl      = "analysis_date + toIntervalDay(30)"
    settings = {
      index_granularity = "8192"
    }
    column "analysis_date" {
      type = "Date"
    }
    column "team_id" {
      type = "Int64"
    }
    column "property_key" {
      type = "String"
    }
    column "event_count" {
      type = "UInt64"
    }
    column "distinct_event_names" {
      type = "UInt32"
    }
    column "total_property_bytes" {
      type = "UInt64"
    }
    column "min_property_bytes" {
      type = "UInt64"
    }
    column "max_property_bytes" {
      type = "UInt64"
    }
    column "avg_property_bytes" {
      type = "Float64"
    }
    column "p50_property_bytes" {
      type = "Float64"
    }
    column "p90_property_bytes" {
      type = "Float64"
    }
    column "p95_property_bytes" {
      type = "Float64"
    }
    column "p99_property_bytes" {
      type = "Float64"
    }
    column "property_size_histogram" {
      type = "Array(Tuple(Float64, Float64, UInt64))"
    }
    column "top_event_names" {
      type = "Array(String)"
    }
    column "sample_rate" {
      type = "Float32"
    }
    column "computed_at" {
      type = "DateTime"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/ops/tables/{shard}/posthog.event_property_daily_stats"
      replica_name = "{replica}"
    }
  }

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

  table "metrics_exemplars" {
    order_by     = ["team_id", "id", "timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    settings = {
      index_granularity = "1024"
    }
    column "team_id" {
      type = "UInt64"
    }
    column "timestamp" {
      type = "DateTime64(3, 'UTC')"
    }
    column "id" {
      type = "UInt64"
    }
    column "value" {
      type = "Float64"
    }
    column "labels_json" {
      type = "String"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/ops/tables/{shard}/posthog.metrics_exemplars"
      replica_name = "{replica}"
    }
  }

  table "metrics_histograms" {
    order_by     = ["team_id", "id", "timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    settings = {
      index_granularity = "1024"
    }
    column "team_id" {
      type = "UInt64"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "timestamp" {
      type = "DateTime64(3, 'UTC')"
    }
    column "id" {
      type = "UInt64"
    }
    column "histogram" {
      type = "String"
    }
    column "version" {
      type = "UInt64"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/ops/tables/{shard}/posthog.metrics_histograms"
      replica_name   = "{replica}"
      version_column = "version"
    }
  }

  table "metrics_label_index" {
    order_by = ["team_id", "metric_name", "label_name", "label_value", "id"]
    settings = {
      deduplicate_merge_projection_mode = "rebuild"
      index_granularity                 = "1024"
    }
    column "team_id" {
      type = "UInt64"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "label_name" {
      type = "LowCardinality(String)"
    }
    column "label_value" {
      type = "String"
    }
    column "id" {
      type = "UInt64"
    }
    projection "by_label_value" {
      query = <<SQL
SELECT team_id, metric_name, label_name, label_value, id
ORDER BY team_id, label_name, label_value, id, metric_name
SQL

    }
    projection "by_id_label" {
      query = <<SQL
SELECT team_id, metric_name, label_name, label_value, id
ORDER BY team_id, id, label_name, metric_name, label_value
SQL

    }
    engine "replicated_replacing_merge_tree" {
      zoo_path     = "/clickhouse/ops/tables/{shard}/posthog.metrics_label_index"
      replica_name = "{replica}"
    }
  }

  table "metrics_metadata" {
    order_by = ["team_id", "metric_family_name"]
    settings = {
      index_granularity = "1024"
    }
    column "team_id" {
      type = "UInt64"
    }
    column "metric_family_name" {
      type = "LowCardinality(String)"
    }
    column "type" {
      type = "LowCardinality(String)"
    }
    column "unit" {
      type = "String"
    }
    column "help" {
      type = "String"
    }
    column "updated_at" {
      type = "DateTime64(3, 'UTC')"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/ops/tables/{shard}/posthog.metrics_metadata"
      replica_name   = "{replica}"
      version_column = "updated_at"
    }
  }

  table "metrics_samples" {
    order_by     = ["team_id", "metric_name", "toStartOfTenMinutes(timestamp)", "id", "timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type  = "UInt64"
      codec = "T64, Default"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "timestamp" {
      type  = "DateTime64(3, 'UTC')"
      codec = "DoubleDelta, Default"
    }
    column "id" {
      type = "UInt64"
    }
    column "value" {
      type  = "Float64"
      codec = "Gorilla(8), Default"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/ops/tables/{shard}/posthog.metrics_samples_new"
      replica_name = "{replica}"
    }
  }

  table "metrics_series" {
    order_by = ["team_id", "metric_name", "id"]
    settings = {
      index_granularity = "1024"
    }
    column "team_id" {
      type = "UInt64"
    }
    column "id" {
      type = "UInt64"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "labels_json" {
      type = "String"
    }
    column "min_time" {
      type = "DateTime64(3, 'UTC')"
    }
    column "max_time" {
      type = "DateTime64(3, 'UTC')"
    }
    projection "by_id" {
      query = <<SQL
SELECT team_id, id, metric_name, labels_json, min_time, max_time
ORDER BY team_id, id
SQL

    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/ops/tables/{shard}/posthog.metrics_series"
      replica_name = "{replica}"
    }
  }

  table "prom_metrics" {
    column "id" {
      type    = "UUID"
      default = "reinterpretAsUUID(sipHash128(metric_name, all_tags))"
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
    primary_key = ["metric_name"]
    order_by    = ["metric_name", "id"]
    settings = {
      index_granularity = "8192"
    }
    column "id" {
      type    = "UUID"
      default = "reinterpretAsUUID(sipHash128(metric_name, all_tags))"
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
    column "initial_query_start_time" {
      type = "DateTime64(6, 'UTC')"
    }
    column "team_id" {
      type = "Int64"
    }
    column "initial_query_id" {
      type = "String"
    }
    column "is_initial_query" {
      type = "SimpleAggregateFunction(max, UInt8)"
    }
    column "hostname" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "user" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "type" {
      type = "SimpleAggregateFunction(max, Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4))"
    }
    column "event_time_microseconds" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "query_duration_ms" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "read_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "read_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "written_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "written_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "result_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "result_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "memory_usage" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "memory_usage_sum" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "peak_threads_usage" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "execution_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "current_database" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "normalized_query_hash" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "query_kind_by_root" {
      type = "SimpleAggregateFunction(max, Tuple(UInt8, String))"
    }
    column "tables" {
      type = "SimpleAggregateFunction(max, Array(String))"
    }
    column "exception_code" {
      type = "SimpleAggregateFunction(max, Int32)"
    }
    column "exception" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "stack_trace" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "ProfileEvents_SelectedRows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_RealTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_OSCPUVirtualTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_UserTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SystemTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedParts" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedMarks" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_NetworkReceiveBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_NetworkSendBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_ReadBufferFromFileDescriptorReadBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_WriteBufferFromFileDescriptorWriteBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3Clients" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3DeleteObjects" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CopyObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3ListObjects" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3HeadObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3GetObjectAttributes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CreateMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3UploadPartCopy" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3UploadPart" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3AbortMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CompleteMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3PutObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3GetObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_ReadBufferFromS3Bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_WriteBufferFromS3Bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "lc_org_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_user_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_session_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_is_impersonated" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_workflow" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_kind" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_route_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_access_method" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_api_key_label" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_api_key_mask" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_query_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_product" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_chargeable" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_request_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_client_query_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_dashboard_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_insight_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_cohort_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_batch_export_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_experiment_feature_flag_key" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_alert_config_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_feature" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_table_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_warehouse_query" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_person_on_events_mode" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_service_name" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_workload" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_query__kind" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_query__query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_modifiers" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__workflow_namespace" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__workflow_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__workflow_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__workflow_run_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__activity_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__activity_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__attempt" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_dagster__job_name" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_dagster__run_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_dagster__owner" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_metric_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_execution_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_metric_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_funnel_order_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_exposures_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_metric_events_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_query_surface" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_precompute_table" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_query_group_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_precompute_skip_reason" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_scan_date_from" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_scan_date_to" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_precompute_window_start" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_precompute_window_end" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_plan_fingerprint" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_estimated_rows" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_estimated_bytes" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "query_id" {
      type = "String"
    }
    column "event_time" {
      type = "DateTime('UTC')"
    }
    column "event_date" {
      type = "Date"
    }
    column "query_start_time" {
      type = "DateTime('UTC')"
    }
    column "query_start_time_microseconds" {
      type = "DateTime64(6, 'UTC')"
    }
    column "query_kind" {
      type = "LowCardinality(String)"
    }
    column "formatted_query" {
      type = "String"
    }
    column "query_shape" {
      type = "String"
    }
    column "hogql_shape" {
      type = "String"
    }
    column "exception_name" {
      type = "String"
    }
    column "ProfileEvents" {
      type = "Map(String, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "ops"
      remote_database = "posthog"
      remote_table    = "sharded_query_log_archive_v3"
    }
  }

  table "query_log_archive_v3_buffer" {
    column "initial_query_start_time" {
      type = "DateTime64(6, 'UTC')"
    }
    column "team_id" {
      type = "Int64"
    }
    column "initial_query_id" {
      type = "String"
    }
    column "is_initial_query" {
      type = "SimpleAggregateFunction(max, UInt8)"
    }
    column "hostname" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "user" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "type" {
      type = "SimpleAggregateFunction(max, Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4))"
    }
    column "event_time_microseconds" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "query_duration_ms" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "read_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "read_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "written_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "written_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "result_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "result_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "memory_usage" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "memory_usage_sum" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "peak_threads_usage" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "execution_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "current_database" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "normalized_query_hash" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "query_kind_by_root" {
      type = "SimpleAggregateFunction(max, Tuple(UInt8, String))"
    }
    column "tables" {
      type = "SimpleAggregateFunction(max, Array(String))"
    }
    column "exception_code" {
      type = "SimpleAggregateFunction(max, Int32)"
    }
    column "exception" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "stack_trace" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "ProfileEvents_SelectedRows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_RealTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_OSCPUVirtualTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_UserTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SystemTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedParts" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedMarks" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_NetworkReceiveBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_NetworkSendBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_ReadBufferFromFileDescriptorReadBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_WriteBufferFromFileDescriptorWriteBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3Clients" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3DeleteObjects" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CopyObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3ListObjects" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3HeadObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3GetObjectAttributes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CreateMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3UploadPartCopy" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3UploadPart" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3AbortMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CompleteMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3PutObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3GetObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_ReadBufferFromS3Bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_WriteBufferFromS3Bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "lc_org_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_user_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_session_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_is_impersonated" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_workflow" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_kind" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_route_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_access_method" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_api_key_label" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_api_key_mask" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_query_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_product" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_chargeable" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_request_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_client_query_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_dashboard_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_insight_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_cohort_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_batch_export_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_experiment_feature_flag_key" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_alert_config_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_feature" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_table_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_warehouse_query" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_person_on_events_mode" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_service_name" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_workload" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_query__kind" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_query__query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_modifiers" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__workflow_namespace" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__workflow_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__workflow_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__workflow_run_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__activity_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__activity_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__attempt" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_dagster__job_name" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_dagster__run_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_dagster__owner" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_metric_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_execution_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_metric_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_funnel_order_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_exposures_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_metric_events_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_query_surface" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_precompute_table" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_query_group_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_precompute_skip_reason" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_scan_date_from" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_scan_date_to" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_precompute_window_start" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_precompute_window_end" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_plan_fingerprint" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_estimated_rows" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_estimated_bytes" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    engine "buffer" {
      database   = "posthog"
      table      = "sharded_query_log_archive_v3"
      num_layers = 16
      min_time   = 10
      max_time   = 60
      min_rows   = 10000
      max_rows   = 1000000
      min_bytes  = 10000000
      max_bytes  = 100000000
    }
  }

  table "sharded_query_log_archive_v3" {
    order_by     = ["toStartOfHour(initial_query_start_time)", "team_id", "initial_query_start_time", "initial_query_id"]
    partition_by = "toYYYYMM(initial_query_start_time)"
    settings = {
      index_granularity = "8192"
    }
    column "initial_query_start_time" {
      type = "DateTime64(6, 'UTC')"
    }
    column "team_id" {
      type = "Int64"
    }
    column "initial_query_id" {
      type = "String"
    }
    column "is_initial_query" {
      type = "SimpleAggregateFunction(max, UInt8)"
    }
    column "hostname" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "user" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "type" {
      type = "SimpleAggregateFunction(max, Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4))"
    }
    column "event_time_microseconds" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "query_duration_ms" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "read_rows" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "read_bytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "written_rows" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "written_bytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "result_rows" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "result_bytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "memory_usage" {
      type  = "SimpleAggregateFunction(max, UInt64)"
      codec = "T64, Default"
    }
    column "memory_usage_sum" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "peak_threads_usage" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "execution_count" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "current_database" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "query" {
      type = "SimpleAggregateFunction(max, String)"
      ttl  = "toDateTime(initial_query_start_time) + toIntervalMonth(3)"
    }
    column "normalized_query_hash" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "query_kind_by_root" {
      type = "SimpleAggregateFunction(max, Tuple(UInt8, String))"
    }
    column "tables" {
      type = "SimpleAggregateFunction(max, Array(String))"
    }
    column "exception_code" {
      type = "SimpleAggregateFunction(max, Int32)"
    }
    column "exception" {
      type = "SimpleAggregateFunction(max, String)"
      ttl  = "toDateTime(initial_query_start_time) + toIntervalMonth(3)"
    }
    column "stack_trace" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "ProfileEvents_SelectedRows" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_SelectedBytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_RealTimeMicroseconds" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_OSCPUVirtualTimeMicroseconds" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_UserTimeMicroseconds" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_SystemTimeMicroseconds" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_SelectedParts" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_SelectedMarks" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_NetworkReceiveBytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_NetworkSendBytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_ReadBufferFromFileDescriptorReadBytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_WriteBufferFromFileDescriptorWriteBytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3Clients" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3DeleteObjects" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3CopyObject" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3ListObjects" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3HeadObject" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3GetObjectAttributes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3CreateMultipartUpload" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3UploadPartCopy" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3UploadPart" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3AbortMultipartUpload" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3CompleteMultipartUpload" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3PutObject" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_S3GetObject" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_ReadBufferFromS3Bytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "ProfileEvents_WriteBufferFromS3Bytes" {
      type  = "SimpleAggregateFunction(sum, UInt64)"
      codec = "T64, Default"
    }
    column "lc_org_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_user_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_session_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_is_impersonated" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_workflow" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_kind" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_route_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_access_method" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_api_key_label" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_api_key_mask" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_query_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_product" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_chargeable" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_request_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_client_query_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_dashboard_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_insight_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_cohort_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_batch_export_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_experiment_feature_flag_key" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_alert_config_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_feature" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_table_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_warehouse_query" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_person_on_events_mode" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_service_name" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_workload" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_query__kind" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_query__query" {
      type = "SimpleAggregateFunction(max, String)"
      ttl  = "toDateTime(initial_query_start_time) + toIntervalMonth(3)"
    }
    column "lc_query" {
      type = "SimpleAggregateFunction(max, String)"
      ttl  = "toDateTime(initial_query_start_time) + toIntervalMonth(3)"
    }
    column "lc_modifiers" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__workflow_namespace" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__workflow_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__workflow_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__workflow_run_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__activity_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__activity_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__attempt" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_dagster__job_name" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_dagster__run_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_dagster__owner" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_metric_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_execution_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_metric_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_funnel_order_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_exposures_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_metric_events_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_query_surface" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_precompute_table" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_query_group_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_precompute_skip_reason" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_scan_date_from" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_scan_date_to" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_precompute_window_start" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_precompute_window_end" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_plan_fingerprint" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_estimated_rows" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_estimated_bytes" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "query_id" {
      type  = "String"
      alias = "initial_query_id"
    }
    column "event_time" {
      type  = "DateTime('UTC')"
      alias = "toDateTime(event_time_microseconds)"
    }
    column "event_date" {
      type  = "Date"
      alias = "toDate(event_time_microseconds)"
    }
    column "query_start_time" {
      type  = "DateTime('UTC')"
      alias = "toDateTime(initial_query_start_time)"
    }
    column "query_start_time_microseconds" {
      type  = "DateTime64(6, 'UTC')"
      alias = "initial_query_start_time"
    }
    column "query_kind" {
      type  = "LowCardinality(String)"
      alias = "tupleElement(query_kind_by_root, 2)"
    }
    column "formatted_query" {
      type  = "String"
      alias = "''"
    }
    column "query_shape" {
      type  = "String"
      alias = "normalizeQuery(query)"
    }
    column "hogql_shape" {
      type  = "String"
      alias = "normalizeQuery(lc_query__query)"
    }
    column "exception_name" {
      type  = "String"
      alias = "errorCodeToName(exception_code)"
    }
    column "ProfileEvents" {
      type  = "Map(String, UInt64)"
      alias = "map('SelectedRows', ProfileEvents_SelectedRows, 'SelectedBytes', ProfileEvents_SelectedBytes, 'RealTimeMicroseconds', ProfileEvents_RealTimeMicroseconds, 'OSCPUVirtualTimeMicroseconds', ProfileEvents_OSCPUVirtualTimeMicroseconds, 'UserTimeMicroseconds', ProfileEvents_UserTimeMicroseconds, 'SystemTimeMicroseconds', ProfileEvents_SystemTimeMicroseconds, 'SelectedParts', ProfileEvents_SelectedParts, 'SelectedMarks', ProfileEvents_SelectedMarks, 'NetworkReceiveBytes', ProfileEvents_NetworkReceiveBytes, 'NetworkSendBytes', ProfileEvents_NetworkSendBytes, 'ReadBufferFromFileDescriptorReadBytes', ProfileEvents_ReadBufferFromFileDescriptorReadBytes, 'WriteBufferFromFileDescriptorWriteBytes', ProfileEvents_WriteBufferFromFileDescriptorWriteBytes, 'S3Clients', ProfileEvents_S3Clients, 'S3DeleteObjects', ProfileEvents_S3DeleteObjects, 'S3CopyObject', ProfileEvents_S3CopyObject, 'S3ListObjects', ProfileEvents_S3ListObjects, 'S3HeadObject', ProfileEvents_S3HeadObject, 'S3GetObjectAttributes', ProfileEvents_S3GetObjectAttributes, 'S3CreateMultipartUpload', ProfileEvents_S3CreateMultipartUpload, 'S3UploadPartCopy', ProfileEvents_S3UploadPartCopy, 'S3UploadPart', ProfileEvents_S3UploadPart, 'S3AbortMultipartUpload', ProfileEvents_S3AbortMultipartUpload, 'S3CompleteMultipartUpload', ProfileEvents_S3CompleteMultipartUpload, 'S3PutObject', ProfileEvents_S3PutObject, 'S3GetObject', ProfileEvents_S3GetObject, 'ReadBufferFromS3Bytes', ProfileEvents_ReadBufferFromS3Bytes, 'WriteBufferFromS3Bytes', ProfileEvents_WriteBufferFromS3Bytes)"
    }
    index "initial_query_start_time_minmax" {
      expr        = "initial_query_start_time"
      type        = "minmax"
      granularity = 1
    }
    index "event_date_minmax" {
      expr        = "toDate(event_time_microseconds)"
      type        = "minmax"
      granularity = 1
    }
    index "event_time_minmax" {
      expr        = "toDateTime(event_time_microseconds)"
      type        = "minmax"
      granularity = 1
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.sharded_query_log_archive_v3_by_chain"
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
      zoo_path     = "/clickhouse/tables/ops/{shard}/posthog.tophog_new"
      replica_name = "{replica}"
    }
  }

  table "writable_prom_metrics" {
    column "id" {
      type    = "UUID"
      default = "reinterpretAsUUID(sipHash128(metric_name, all_tags))"
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
      type    = "UUID"
      default = "reinterpretAsUUID(sipHash128(metric_name, all_tags))"
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

  table "writable_query_log_archive_v3" {
    column "initial_query_start_time" {
      type = "DateTime64(6, 'UTC')"
    }
    column "team_id" {
      type = "Int64"
    }
    column "initial_query_id" {
      type = "String"
    }
    column "is_initial_query" {
      type = "SimpleAggregateFunction(max, UInt8)"
    }
    column "hostname" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "user" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "type" {
      type = "SimpleAggregateFunction(max, Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4))"
    }
    column "event_time_microseconds" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "query_duration_ms" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "read_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "read_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "written_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "written_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "result_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "result_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "memory_usage" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "memory_usage_sum" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "peak_threads_usage" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "execution_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "current_database" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "normalized_query_hash" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "query_kind_by_root" {
      type = "SimpleAggregateFunction(max, Tuple(UInt8, String))"
    }
    column "tables" {
      type = "SimpleAggregateFunction(max, Array(String))"
    }
    column "exception_code" {
      type = "SimpleAggregateFunction(max, Int32)"
    }
    column "exception" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "stack_trace" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "ProfileEvents_SelectedRows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_RealTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_OSCPUVirtualTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_UserTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SystemTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedParts" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedMarks" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_NetworkReceiveBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_NetworkSendBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_ReadBufferFromFileDescriptorReadBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_WriteBufferFromFileDescriptorWriteBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3Clients" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3DeleteObjects" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CopyObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3ListObjects" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3HeadObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3GetObjectAttributes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CreateMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3UploadPartCopy" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3UploadPart" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3AbortMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CompleteMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3PutObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3GetObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_ReadBufferFromS3Bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_WriteBufferFromS3Bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "lc_org_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_user_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_session_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_is_impersonated" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_workflow" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_kind" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_route_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_access_method" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_api_key_label" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_api_key_mask" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_query_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_product" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_chargeable" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_request_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_client_query_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_dashboard_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_insight_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_cohort_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_batch_export_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_experiment_feature_flag_key" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_alert_config_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_feature" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_table_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_warehouse_query" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_person_on_events_mode" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_service_name" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_workload" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_query__kind" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_query__query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_modifiers" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__workflow_namespace" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__workflow_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__workflow_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__workflow_run_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__activity_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__activity_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__attempt" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_dagster__job_name" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_dagster__run_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_dagster__owner" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_metric_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_execution_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_metric_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_funnel_order_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_exposures_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_metric_events_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_query_surface" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_precompute_table" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_query_group_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_precompute_skip_reason" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_scan_date_from" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_scan_date_to" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_precompute_window_start" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_precompute_window_end" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_plan_fingerprint" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_estimated_rows" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_estimated_bytes" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    engine "distributed" {
      cluster_name    = "ops"
      remote_database = "posthog"
      remote_table    = "query_log_archive_v3_buffer"
    }
  }

  materialized_view "metrics_label_index_from_series_mv" {
    to_table = "posthog.metrics_label_index"
    query    = <<SQL
SELECT
  team_id,
  metric_name,
  tupleElement(label_pair, 1) AS label_name,
  tupleElement(label_pair, 2) AS label_value,
  id
FROM
  posthog.metrics_series ARRAY JOIN JSONExtractKeysAndValues(labels_json, 'String') AS label_pair
SQL

    column "team_id" {
      type = "UInt64"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "label_name" {
      type = "LowCardinality(String)"
    }
    column "label_value" {
      type = "String"
    }
    column "id" {
      type = "UInt64"
    }
  }

  materialized_view "ops_query_log_archive_v3_mv" {
    to_table = "posthog.writable_query_log_archive_v3"
    query    = <<SQL
WITH
  JSONExtract(ql.log_comment, 'Tuple(team_id Int64, org_id String, user_id Int64, session_id String, is_impersonated Bool, workflow String, kind String, id String, route_id String, access_method String, api_key_label String, api_key_mask String, query_type String, product String, chargeable Bool, name String, request_name String, client_query_id String, dashboard_id Int64, insight_id Int64, cohort_id Int64, batch_export_id String, experiment_id Int64, experiment_feature_flag_key String, alert_config_id String, feature String, table_id String, warehouse_query Bool, person_on_events_mode String, service_name String, workload String, experiment_name String, experiment_metric_name String, experiment_execution_path String, experiment_metric_type String, experiment_funnel_order_type String, experiment_exposures_path String, experiment_metric_events_path String, experiment_query_surface String, experiment_precompute_table String, experiment_query_group_id String, experiment_precompute_skip_reason String, experiment_scan_date_from String, experiment_scan_date_to String, precompute_window_start String, precompute_window_end String, plan_fingerprint String, estimated_rows Int64, estimated_bytes Int64, temporal Tuple(workflow_namespace String, workflow_type String, workflow_id String, workflow_run_id String, activity_type String, activity_id String, attempt Int64), dagster Tuple(job_name String, run_id String, tags Tuple(owner String)), query Tuple(kind String, query String, source Tuple(kind String, query String)))') AS lc
SELECT
  if(
    empty(ql.initial_query_id),
    ql.query_start_time_microseconds,
    ql.initial_query_start_time_microseconds
  ) AS initial_query_start_time,
  lc.team_id AS team_id,
  if(empty(ql.initial_query_id), ql.query_id, ql.initial_query_id) AS initial_query_id,
  ql.is_initial_query AS is_initial_query,
  if(ql.is_initial_query, ql.hostname, '') AS hostname,
  ql.user AS user,
  ql.type AS type,
  ql.event_time_microseconds AS event_time_microseconds,
  if(ql.is_initial_query, ql.query_duration_ms, 0) AS query_duration_ms,
  if(ql.is_initial_query, ql.read_rows, 0) AS read_rows,
  if(ql.is_initial_query, ql.read_bytes, 0) AS read_bytes,
  if(ql.is_initial_query, ql.written_rows, 0) AS written_rows,
  if(ql.is_initial_query, ql.written_bytes, 0) AS written_bytes,
  if(ql.is_initial_query, ql.result_rows, 0) AS result_rows,
  if(ql.is_initial_query, ql.result_bytes, 0) AS result_bytes,
  ql.memory_usage AS memory_usage,
  ql.memory_usage AS memory_usage_sum,
  ql.peak_threads_usage AS peak_threads_usage,
  1 AS execution_count,
  ql.current_database AS current_database,
  if(ql.is_initial_query, ql.query, '') AS query,
  if(ql.is_initial_query, ql.normalized_query_hash, 0) AS normalized_query_hash,
  tuple(ql.is_initial_query, ql.query_kind) AS query_kind_by_root,
  if(ql.is_initial_query, ql.tables, []) AS tables,
  if(ql.is_initial_query, ql.exception_code, 0) AS exception_code,
  if(ql.is_initial_query, ql.exception, '') AS exception,
  if(ql.is_initial_query, ql.stack_trace, '') AS stack_trace,
  if(ql.is_initial_query, ql.ProfileEvents['SelectedRows'], 0) AS ProfileEvents_SelectedRows,
  if(ql.is_initial_query, ql.ProfileEvents['SelectedBytes'], 0) AS ProfileEvents_SelectedBytes,
  ql.ProfileEvents['RealTimeMicroseconds'] AS ProfileEvents_RealTimeMicroseconds,
  ql.ProfileEvents['OSCPUVirtualTimeMicroseconds'] AS ProfileEvents_OSCPUVirtualTimeMicroseconds,
  ql.ProfileEvents['UserTimeMicroseconds'] AS ProfileEvents_UserTimeMicroseconds,
  ql.ProfileEvents['SystemTimeMicroseconds'] AS ProfileEvents_SystemTimeMicroseconds,
  ql.ProfileEvents['SelectedParts'] AS ProfileEvents_SelectedParts,
  ql.ProfileEvents['SelectedMarks'] AS ProfileEvents_SelectedMarks,
  ql.ProfileEvents['NetworkReceiveBytes'] AS ProfileEvents_NetworkReceiveBytes,
  ql.ProfileEvents['NetworkSendBytes'] AS ProfileEvents_NetworkSendBytes,
  ql.ProfileEvents['ReadBufferFromFileDescriptorReadBytes'] AS ProfileEvents_ReadBufferFromFileDescriptorReadBytes,
  ql.ProfileEvents['WriteBufferFromFileDescriptorWriteBytes'] AS ProfileEvents_WriteBufferFromFileDescriptorWriteBytes,
  ql.ProfileEvents['S3Clients'] AS ProfileEvents_S3Clients,
  ql.ProfileEvents['S3DeleteObjects'] AS ProfileEvents_S3DeleteObjects,
  ql.ProfileEvents['S3CopyObject'] AS ProfileEvents_S3CopyObject,
  ql.ProfileEvents['S3ListObjects'] AS ProfileEvents_S3ListObjects,
  ql.ProfileEvents['S3HeadObject'] AS ProfileEvents_S3HeadObject,
  ql.ProfileEvents['S3GetObjectAttributes'] AS ProfileEvents_S3GetObjectAttributes,
  ql.ProfileEvents['S3CreateMultipartUpload'] AS ProfileEvents_S3CreateMultipartUpload,
  ql.ProfileEvents['S3UploadPartCopy'] AS ProfileEvents_S3UploadPartCopy,
  ql.ProfileEvents['S3UploadPart'] AS ProfileEvents_S3UploadPart,
  ql.ProfileEvents['S3AbortMultipartUpload'] AS ProfileEvents_S3AbortMultipartUpload,
  ql.ProfileEvents['S3CompleteMultipartUpload'] AS ProfileEvents_S3CompleteMultipartUpload,
  ql.ProfileEvents['S3PutObject'] AS ProfileEvents_S3PutObject,
  ql.ProfileEvents['S3GetObject'] AS ProfileEvents_S3GetObject,
  ql.ProfileEvents['ReadBufferFromS3Bytes'] AS ProfileEvents_ReadBufferFromS3Bytes,
  ql.ProfileEvents['WriteBufferFromS3Bytes'] AS ProfileEvents_WriteBufferFromS3Bytes,
  lc.org_id AS lc_org_id,
  lc.user_id AS lc_user_id,
  lc.session_id AS lc_session_id,
  lc.is_impersonated AS lc_is_impersonated,
  lc.workflow AS lc_workflow,
  lc.kind AS lc_kind,
  lc.id AS lc_id,
  lc.route_id AS lc_route_id,
  lc.access_method AS lc_access_method,
  lc.api_key_label AS lc_api_key_label,
  lc.api_key_mask AS lc_api_key_mask,
  lc.query_type AS lc_query_type,
  lc.product AS lc_product,
  lc.chargeable AS lc_chargeable,
  lc.name AS lc_name,
  lc.request_name AS lc_request_name,
  lc.client_query_id AS lc_client_query_id,
  lc.dashboard_id AS lc_dashboard_id,
  lc.insight_id AS lc_insight_id,
  lc.cohort_id AS lc_cohort_id,
  lc.batch_export_id AS lc_batch_export_id,
  lc.experiment_id AS lc_experiment_id,
  lc.experiment_feature_flag_key AS lc_experiment_feature_flag_key,
  lc.alert_config_id AS lc_alert_config_id,
  lc.feature AS lc_feature,
  lc.table_id AS lc_table_id,
  lc.warehouse_query AS lc_warehouse_query,
  lc.person_on_events_mode AS lc_person_on_events_mode,
  lc.service_name AS lc_service_name,
  lc.workload AS lc_workload,
  if(notEmpty(lc.query.source.kind), lc.query.source.kind, lc.query.kind) AS lc_query__kind,
  if(
    ql.is_initial_query,
    if(notEmpty(lc.query.source.kind), lc.query.source.query, lc.query.query),
    ''
  ) AS lc_query__query,
  if(ql.is_initial_query, JSONExtractRaw(ql.log_comment, 'query'), '') AS lc_query,
  if(ql.is_initial_query, JSONExtractRaw(ql.log_comment, 'modifiers'), '') AS lc_modifiers,
  lc.temporal.workflow_namespace AS lc_temporal__workflow_namespace,
  lc.temporal.workflow_type AS lc_temporal__workflow_type,
  lc.temporal.workflow_id AS lc_temporal__workflow_id,
  lc.temporal.workflow_run_id AS lc_temporal__workflow_run_id,
  lc.temporal.activity_type AS lc_temporal__activity_type,
  lc.temporal.activity_id AS lc_temporal__activity_id,
  lc.temporal.attempt AS lc_temporal__attempt,
  lc.dagster.job_name AS lc_dagster__job_name,
  lc.dagster.run_id AS lc_dagster__run_id,
  lc.dagster.tags.owner AS lc_dagster__owner,
  lc.experiment_name AS lc_experiment_name,
  lc.experiment_metric_name AS lc_experiment_metric_name,
  lc.experiment_execution_path AS lc_experiment_execution_path,
  lc.experiment_metric_type AS lc_experiment_metric_type,
  lc.experiment_funnel_order_type AS lc_experiment_funnel_order_type,
  lc.experiment_exposures_path AS lc_experiment_exposures_path,
  lc.experiment_metric_events_path AS lc_experiment_metric_events_path,
  lc.experiment_query_surface AS lc_experiment_query_surface,
  lc.experiment_precompute_table AS lc_experiment_precompute_table,
  lc.experiment_query_group_id AS lc_experiment_query_group_id,
  lc.experiment_precompute_skip_reason AS lc_experiment_precompute_skip_reason,
  lc.experiment_scan_date_from AS lc_experiment_scan_date_from,
  lc.experiment_scan_date_to AS lc_experiment_scan_date_to,
  lc.precompute_window_start AS lc_precompute_window_start,
  lc.precompute_window_end AS lc_precompute_window_end,
  lc.plan_fingerprint AS lc_plan_fingerprint,
  lc.estimated_rows AS lc_estimated_rows,
  lc.estimated_bytes AS lc_estimated_bytes
FROM system.query_log AS ql
WHERE ql.type != 'QueryStart'
SQL

    column "initial_query_start_time" {
      type = "DateTime64(6, 'UTC')"
    }
    column "team_id" {
      type = "Int64"
    }
    column "initial_query_id" {
      type = "String"
    }
    column "is_initial_query" {
      type = "SimpleAggregateFunction(max, UInt8)"
    }
    column "hostname" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "user" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "type" {
      type = "SimpleAggregateFunction(max, Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4))"
    }
    column "event_time_microseconds" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "query_duration_ms" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "read_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "read_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "written_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "written_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "result_rows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "result_bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "memory_usage" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "memory_usage_sum" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "peak_threads_usage" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "execution_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "current_database" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "normalized_query_hash" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "query_kind_by_root" {
      type = "SimpleAggregateFunction(max, Tuple(UInt8, String))"
    }
    column "tables" {
      type = "SimpleAggregateFunction(max, Array(String))"
    }
    column "exception_code" {
      type = "SimpleAggregateFunction(max, Int32)"
    }
    column "exception" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "stack_trace" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "ProfileEvents_SelectedRows" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_RealTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_OSCPUVirtualTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_UserTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SystemTimeMicroseconds" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedParts" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_SelectedMarks" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_NetworkReceiveBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_NetworkSendBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_ReadBufferFromFileDescriptorReadBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_WriteBufferFromFileDescriptorWriteBytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3Clients" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3DeleteObjects" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CopyObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3ListObjects" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3HeadObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3GetObjectAttributes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CreateMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3UploadPartCopy" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3UploadPart" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3AbortMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3CompleteMultipartUpload" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3PutObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_S3GetObject" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_ReadBufferFromS3Bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "ProfileEvents_WriteBufferFromS3Bytes" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "lc_org_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_user_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_session_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_is_impersonated" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_workflow" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_kind" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_route_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_access_method" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_api_key_label" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_api_key_mask" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_query_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_product" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_chargeable" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_request_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_client_query_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_dashboard_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_insight_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_cohort_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_batch_export_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_id" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_experiment_feature_flag_key" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_alert_config_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_feature" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_table_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_warehouse_query" {
      type = "SimpleAggregateFunction(max, Bool)"
    }
    column "lc_person_on_events_mode" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_service_name" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_workload" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_query__kind" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_query__query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_query" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_modifiers" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__workflow_namespace" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__workflow_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__workflow_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__workflow_run_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__activity_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_temporal__activity_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_temporal__attempt" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_dagster__job_name" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_dagster__run_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_dagster__owner" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_metric_name" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_execution_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_metric_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_funnel_order_type" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_exposures_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_metric_events_path" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_query_surface" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_precompute_table" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_query_group_id" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_precompute_skip_reason" {
      type = "SimpleAggregateFunction(max, LowCardinality(String))"
    }
    column "lc_experiment_scan_date_from" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_experiment_scan_date_to" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_precompute_window_start" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_precompute_window_end" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_plan_fingerprint" {
      type = "SimpleAggregateFunction(max, String)"
    }
    column "lc_estimated_rows" {
      type = "SimpleAggregateFunction(max, Int64)"
    }
    column "lc_estimated_bytes" {
      type = "SimpleAggregateFunction(max, Int64)"
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
}
