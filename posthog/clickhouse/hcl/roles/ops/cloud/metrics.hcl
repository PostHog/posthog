# OPS role, cloud envs — the Prometheus-style metrics suite and the
# event-property daily rollup. dev, prod-us and prod-eu run it identically.

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
  materialized_view "metrics_label_index_from_series_mv" {
    to_table = "posthog.metrics_label_index"
    query = file("sql/metrics_label_index_from_series_mv.sql")
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
}
