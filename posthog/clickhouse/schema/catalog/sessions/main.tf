variable "node" {
  description = "The server these objects live on: { name, host, port, leader }. Null puts them on the provider's host."
  type        = any
  default     = null
}

variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "objects" {
  description = "Names of the objects to create."
  type        = set(string)
}

variable "test" {
  description = "Use the definitions the test suite expects."
  type        = bool
  default     = false
}

variable "deployment" { type = any }

locals {
  deployment = merge({ overrides = {} }, var.deployment)
}

# Reads from events. Those must exist on the node first.

locals {
}

# Column lists that more than one object uses.

locals {
  sharded_sessions_columns = [
    { name = "session_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "SimpleAggregateFunction(any, String)" },
    { name = "min_timestamp", type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))" },
    { name = "max_timestamp", type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))" },
    { name = "urls", type = "SimpleAggregateFunction(groupUniqArrayArray, Array(String))" },
    { name = "entry_url", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "exit_url", type = "AggregateFunction(argMax, String, DateTime64(6, 'UTC'))" },
    { name = "initial_referring_domain", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_utm_source", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_utm_campaign", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_utm_medium", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_utm_term", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_utm_content", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_gclid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_gad_source", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_gclsrc", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_dclid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_gbraid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_wbraid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_fbclid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_msclkid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_twclid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_li_fat_id", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_mc_cid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_igshid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_ttclid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_epik", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_qclid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "initial_sccid", type = "AggregateFunction(argMin, String, DateTime64(6, 'UTC'))" },
    { name = "event_count_map", type = "SimpleAggregateFunction(sumMap, Map(String, Int64))" },
    { name = "pageview_count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "autocapture_count", type = "SimpleAggregateFunction(sum, Int64)" },
  ]
}

module "sharded_sessions_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "sessions"
  database = var.database
  columns  = local.sharded_sessions_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toYYYYMM(min_timestamp)"
    order_by     = "(toStartOfDay(min_timestamp), team_id, session_id)"
    settings     = "index_granularity = 512"
  }
  sharding_key = "sipHash64(session_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.sessions"
    cluster     = "posthog"
  }, local.deployment)
}

# Tables that hold data, and the materialized views between them.

module "sessions_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "sessions_mv")
  database = var.database
  name     = "sessions_mv"
  to_table = "${var.database}.writable_sessions"
  query    = <<-SQL
    SELECT
        `$session_id` AS session_id,
        team_id,
        any(distinct_id) AS distinct_id,
        min(timestamp) AS min_timestamp,
        max(timestamp) AS max_timestamp,
        groupUniqArray(replaceRegexpAll(JSONExtractRaw(properties, '$current_url'), '^"|"$', '')) AS urls,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, '$current_url'), '^"|"$', ''), timestamp) AS entry_url,
        argMaxState(replaceRegexpAll(JSONExtractRaw(properties, '$current_url'), '^"|"$', ''), timestamp) AS exit_url,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, '$referring_domain'), '^"|"$', ''), timestamp) AS initial_referring_domain,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_source'), '^"|"$', ''), timestamp) AS initial_utm_source,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_campaign'), '^"|"$', ''), timestamp) AS initial_utm_campaign,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_medium'), '^"|"$', ''), timestamp) AS initial_utm_medium,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_term'), '^"|"$', ''), timestamp) AS initial_utm_term,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'utm_content'), '^"|"$', ''), timestamp) AS initial_utm_content,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gclid'), '^"|"$', ''), timestamp) AS initial_gclid,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gad_source'), '^"|"$', ''), timestamp) AS initial_gad_source,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gclsrc'), '^"|"$', ''), timestamp) AS initial_gclsrc,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'dclid'), '^"|"$', ''), timestamp) AS initial_dclid,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'gbraid'), '^"|"$', ''), timestamp) AS initial_gbraid,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'wbraid'), '^"|"$', ''), timestamp) AS initial_wbraid,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'fbclid'), '^"|"$', ''), timestamp) AS initial_fbclid,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'msclkid'), '^"|"$', ''), timestamp) AS initial_msclkid,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'twclid'), '^"|"$', ''), timestamp) AS initial_twclid,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'li_fat_id'), '^"|"$', ''), timestamp) AS initial_li_fat_id,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'mc_cid'), '^"|"$', ''), timestamp) AS initial_mc_cid,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'igshid'), '^"|"$', ''), timestamp) AS initial_igshid,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'ttclid'), '^"|"$', ''), timestamp) AS initial_ttclid,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'epik'), '^"|"$', ''), timestamp) AS initial_epik,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'qclid'), '^"|"$', ''), timestamp) AS initial_qclid,
        argMinState(replaceRegexpAll(JSONExtractRaw(properties, 'sccid'), '^"|"$', ''), timestamp) AS initial_sccid,
        sumMap(CAST(([event], [1]), 'Map(String, UInt64)')) AS event_count_map,
        sumIf(1, event = '$pageview') AS pageview_count,
        sumIf(1, event = '$autocapture') AS autocapture_count
    FROM ${var.database}.sharded_events
    WHERE (`$session_id` IS NOT NULL) AND (`$session_id` != '') AND (team_id IN (1, 2, 13610, 19279, 21173, 29929, 32050, 9910, 11775, 21129, 31490))
    GROUP BY
        `$session_id`,
        team_id
  SQL
  override = try(local.deployment.overrides["sessions_mv"], {})

  depends_on = [
    module.sharded_sessions_family,
  ]
}

# Distributed tables, views and dictionaries that queries read from.


module "sessions_v" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "sessions_v")
  database = var.database
  name     = "sessions_v"
  query    = <<-SQL
    SELECT
        session_id,
        team_id,
        any(distinct_id) AS distinct_id,
        min(min_timestamp) AS min_timestamp,
        max(max_timestamp) AS max_timestamp,
        arrayDistinct(arrayFlatten(groupArray(urls))) AS urls,
        argMinMerge(entry_url) AS entry_url,
        argMaxMerge(exit_url) AS exit_url,
        argMinMerge(initial_utm_source) AS initial_utm_source,
        argMinMerge(initial_utm_campaign) AS initial_utm_campaign,
        argMinMerge(initial_utm_medium) AS initial_utm_medium,
        argMinMerge(initial_utm_term) AS initial_utm_term,
        argMinMerge(initial_utm_content) AS initial_utm_content,
        argMinMerge(initial_referring_domain) AS initial_referring_domain,
        argMinMerge(initial_gclid) AS initial_gclid,
        argMinMerge(initial_gad_source) AS initial_gad_source,
        argMinMerge(initial_gclsrc) AS initial_gclsrc,
        argMinMerge(initial_dclid) AS initial_dclid,
        argMinMerge(initial_gbraid) AS initial_gbraid,
        argMinMerge(initial_wbraid) AS initial_wbraid,
        argMinMerge(initial_fbclid) AS initial_fbclid,
        argMinMerge(initial_msclkid) AS initial_msclkid,
        argMinMerge(initial_twclid) AS initial_twclid,
        argMinMerge(initial_li_fat_id) AS initial_li_fat_id,
        argMinMerge(initial_mc_cid) AS initial_mc_cid,
        argMinMerge(initial_igshid) AS initial_igshid,
        argMinMerge(initial_ttclid) AS initial_ttclid,
        argMinMerge(initial_epik) AS initial_epik,
        argMinMerge(initial_qclid) AS initial_qclid,
        argMinMerge(initial_sccid) AS initial_sccid,
        sumMap(event_count_map) AS event_count_map,
        sum(pageview_count) AS pageview_count,
        sum(autocapture_count) AS autocapture_count
    FROM ${var.database}.sessions
    GROUP BY
        session_id,
        team_id
  SQL
  override = try(local.deployment.overrides["sessions_v"], {})

  depends_on = [
    module.sharded_sessions_family,
  ]
}
