# OPS prod layer — metrics suite, identical across prod-us and prod-eu
#
# Generated/maintained as the declarative source of truth for the OPS ClickHouse cluster.
# See docs/plans/2026-06-16-ops-cluster-hcl-schema.md. Resolve with: hclexp load -layer <base>,<...>

database "posthog" {
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
    query    = "SELECT team_id, metric_name, tupleElement(label_pair, 1) AS label_name, tupleElement(label_pair, 2) AS label_value, id FROM posthog.metrics_series ARRAY JOIN JSONExtractKeysAndValues(labels_json, 'String') AS label_pair"
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
