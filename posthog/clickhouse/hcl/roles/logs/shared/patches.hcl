# Cloud deltas to the base logs objects (roles/logs/base): the cloud logs
# cluster and its per-shard replication paths, plus prod-only merge settings.

database "posthog" {

  patch_table "log_attributes2" {
    partition_by = "toDate(time_bucket)"
    ttl = "time_bucket + toIntervalDay(15)"
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/log_attributes34"
      replica_name = "{replica}"
    }
  }

  patch_table "log_attributes_distributed" {
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "log_attributes3"
    }
  }

  patch_table "logs_billing_metrics" {
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/logs_billing_metrics"
      replica_name = "{replica}"
    }
  }

  patch_table "logs_billing_metrics_distributed" {
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "logs_billing_metrics"
    }
  }

  patch_table "logs_distributed" {
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "logs34"
    }
  }

  patch_table "logs_kafka_metrics" {
    settings = {
      deduplicate_merge_projection_mode = "rebuild"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/logs_kafka_metrics"
      replica_name = "{replica}"
    }
  }

  patch_table "logs_kafka_metrics_distributed" {
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "logs_kafka_metrics"
    }
  }

  patch_table "logs_volume_buckets_distributed" {
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "logs_volume_buckets"
    }
  }

  patch_table "metric_samples" {
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "metric_samples1"
    }
  }

  patch_table "metric_series" {
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "metric_series1"
    }
  }

}
