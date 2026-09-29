database "posthog" {
  table "person_property_mutation_log_data" {
    extend = "_person_property_mutation_log_columns"
    order_by = ["team_id", "event_uuid"]
    partition_by = "toDate(ingested_at)"
    ttl = "ingested_at + toIntervalDay(30)"
    settings = { index_granularity = "1024", ttl_only_drop_parts = "1" }
    engine "replicated_replacing_merge_tree" {
      zoo_path = "/clickhouse/tables/noshard/posthog.person_property_mutation_log_data"
      replica_name = "{replica}-{shard}"
      version_column = "ingested_at"
    }
  }
}
