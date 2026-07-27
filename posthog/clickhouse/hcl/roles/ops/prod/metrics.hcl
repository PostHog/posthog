# OPS role, prod only — metrics suite + sharded_tophog abstract.

database "posthog" {
  table "sharded_tophog_base" {
    abstract     = true
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
    order_by     = ["team_id", "metric_name", "id", "timestamp"]
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
    column "value" {
      type = "Float64"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/ops/tables/{shard}/posthog.metrics_samples"
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
