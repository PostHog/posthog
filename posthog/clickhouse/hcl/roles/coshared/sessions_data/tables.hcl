# Objects co-hosted by the sessions satellite (both prods) and the local data
# node. Bases are the minimal forms; the data node's storage attributes are
# patch_table blocks in roles/data/local, and the satellite's own storage copies
# of sessions/raw_sessions are override declarations in roles/sessions/shared
# (they carry sample_by, which patches cannot express).
database "posthog" {

  table "web_pre_aggregated_teams" {
    column "team_id" {
      type = "UInt64"
    }
    column "enabled_by" {
      type    = "String"
      default = "'system'"
    }
    column "version" {
      type    = "UInt32"
      default = "toUnixTimestamp(now())"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "web_pre_aggregated_teams"
    }
  }

  dictionary "channel_definition_dict" {
    primary_key = ["domain", "kind"]
    lifetime {
      min = 3000
      max = 3600
    }
    attribute "domain" {
      type = "String"
    }
    attribute "kind" {
      type = "String"
    }
    attribute "domain_type" {
      type = "Nullable(String)"
    }
    attribute "type_if_paid" {
      type = "Nullable(String)"
    }
    attribute "type_if_organic" {
      type = "Nullable(String)"
    }
    source "clickhouse" {
      user  = "dict_reader"
      table = "channel_definition"
    }
    layout "complex_key_hashed" {
    }
  }

  dictionary "web_pre_aggregated_teams_dict" {
    primary_key = ["team_id"]
    lifetime {
      min = 3000
      max = 3600
    }
    attribute "team_id" {
      type = "UInt64"
    }
    source "clickhouse" {
      user  = "dict_reader"
      query = "SELECT     team_id FROM     `web_pre_aggregated_teams` FINAL WHERE version > 0"
    }
    layout "hashed" {
    }
  }

  table "sessions" {
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "SimpleAggregateFunction(any, String)"
    }
    column "min_timestamp" {
      type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
    column "urls" {
      type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))"
    }
    column "entry_url" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "exit_url" {
      type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))"
    }
    column "initial_referring_domain" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_source" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_campaign" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_medium" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_term" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_utm_content" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gad_source" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gclsrc" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_dclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_gbraid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_wbraid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_fbclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_msclkid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_twclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_li_fat_id" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_mc_cid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_igshid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_ttclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_epik" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_qclid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "initial_sccid" {
      type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))"
    }
    column "event_count_map" {
      type = "SimpleAggregateFunction(sumMap, Map(String, Int64))"
    }
    column "pageview_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    column "autocapture_count" {
      type = "SimpleAggregateFunction(sum, Int64)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_sessions"
      sharding_key    = "sipHash64(session_id)"
    }
  }

}
