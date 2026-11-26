# Distributed proxies onto the day-partitioned dimensional tables on the aux cluster. They sit in their own file so
# the events cluster can compose them without the rest of aux_data: it serves every query of a project that reads
# events_json. Their columns come from the abstracts in roles/shared/web_dimensional_columns.hcl.
database "posthog" {
  table "web_bounces_dimensional_preaggregated_by_day" {
    extend = "_web_bounces_dimensional_preaggregated_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_bounces_dimensional_preaggregated_by_day"
      sharding_key    = "sipHash64(job_id)"
    }
  }
  table "web_stats_dimensional_preaggregated_by_day" {
    extend = "_web_stats_dimensional_preaggregated_columns"
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_stats_dimensional_preaggregated_by_day"
      sharding_key    = "sipHash64(job_id)"
    }
  }
}
