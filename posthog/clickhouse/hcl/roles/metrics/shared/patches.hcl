# metrics4_samples overflows to S3 on this cluster. The disk balancer in posthog-cloud-infra moves
# its oldest parts off local disk.
database "posthog" {
  patch_table "metrics4_samples" {
    settings = {
      storage_policy = "s3_tiered"
    }
  }

  # The logs cluster keeps its per-shard path and replica name. This cluster is created by the
  # migration, which uses the single-shard ones.
  patch_table "metrics_kafka_metrics" {
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.metrics_kafka_metrics"
      replica_name = "{replica}-{shard}"
    }
  }
}
