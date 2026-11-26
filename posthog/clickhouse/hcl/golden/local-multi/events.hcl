database "posthog" {
  table "web_bounces_dimensional_preaggregated_by_day" {
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "period_bucket" {
      type = "DateTime"
    }
    column "host" {
      type = "String"
    }
    column "device_type" {
      type = "String"
    }
    column "entry_pathname" {
      type = "String"
    }
    column "end_pathname" {
      type = "String"
    }
    column "browser" {
      type = "String"
    }
    column "os" {
      type = "String"
    }
    column "viewport_width" {
      type = "Int64"
    }
    column "viewport_height" {
      type = "Int64"
    }
    column "referring_domain" {
      type = "String"
    }
    column "utm_source" {
      type = "String"
    }
    column "utm_medium" {
      type = "String"
    }
    column "utm_campaign" {
      type = "String"
    }
    column "utm_term" {
      type = "String"
    }
    column "utm_content" {
      type = "String"
    }
    column "country_code" {
      type = "String"
    }
    column "city_name" {
      type = "String"
    }
    column "region_code" {
      type = "String"
    }
    column "region_name" {
      type = "String"
    }
    column "has_gclid" {
      type = "Bool"
    }
    column "has_gad_source_paid_search" {
      type = "Bool"
    }
    column "has_fbclid" {
      type = "Bool"
    }
    column "mat_metadata_backend" {
      type = "Nullable(String)"
    }
    column "mat_metadata_loggedIn" {
      type = "Nullable(Bool)"
    }
    column "channel_type" {
      type = "LowCardinality(String)"
    }
    column "session_hosts" {
      type = "Array(String)"
    }
    column "persons_uniq_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sessions_uniq_state" {
      type = "AggregateFunction(uniq, String)"
    }
    column "pageviews_count_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "bounces_count_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "total_session_duration_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "total_session_count_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "bounce_eligible_sessions_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_bounces_dimensional_preaggregated_by_day"
      sharding_key    = "sipHash64(job_id)"
    }
  }

  table "web_stats_dimensional_preaggregated_by_day" {
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "period_bucket" {
      type = "DateTime"
    }
    column "host" {
      type = "String"
    }
    column "device_type" {
      type = "String"
    }
    column "pathname" {
      type = "String"
    }
    column "entry_pathname" {
      type = "String"
    }
    column "end_pathname" {
      type = "String"
    }
    column "browser" {
      type = "String"
    }
    column "os" {
      type = "String"
    }
    column "viewport_width" {
      type = "Int64"
    }
    column "viewport_height" {
      type = "Int64"
    }
    column "referring_domain" {
      type = "String"
    }
    column "utm_source" {
      type = "String"
    }
    column "utm_medium" {
      type = "String"
    }
    column "utm_campaign" {
      type = "String"
    }
    column "utm_term" {
      type = "String"
    }
    column "utm_content" {
      type = "String"
    }
    column "country_code" {
      type = "String"
    }
    column "city_name" {
      type = "String"
    }
    column "region_code" {
      type = "String"
    }
    column "region_name" {
      type = "String"
    }
    column "has_gclid" {
      type = "Bool"
    }
    column "has_gad_source_paid_search" {
      type = "Bool"
    }
    column "has_fbclid" {
      type = "Bool"
    }
    column "mat_metadata_backend" {
      type = "Nullable(String)"
    }
    column "mat_metadata_loggedIn" {
      type = "Nullable(Bool)"
    }
    column "channel_type" {
      type = "LowCardinality(String)"
    }
    column "persons_uniq_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sessions_uniq_state" {
      type = "AggregateFunction(uniq, String)"
    }
    column "pageviews_count_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_stats_dimensional_preaggregated_by_day"
      sharding_key    = "sipHash64(job_id)"
    }
  }
}
