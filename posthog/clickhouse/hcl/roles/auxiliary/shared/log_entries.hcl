# The aux log_entries store. Tiering (7-day move to the S3 `cold` volume + s3_tiered
# storage policy) is a deployed-cloud delta in roles/auxiliary/prod/patches.hcl.
database "posthog" {
  table "log_entries_data" {
    extend       = "_log_entries_aux_columns"
    order_by     = ["team_id", "log_source", "log_source_id", "instance_id", "timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalDay(90)"
    settings = {
      index_granularity   = "1024"
      ttl_only_drop_parts = "1"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.log_entries_data"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }
}
