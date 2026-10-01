# Distributed tables, views and dictionaries that queries read from.

module "sessions" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "sessions")
  database = var.database
  name     = "sessions"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_sessions', sipHash64(session_id))"
  columns  = local.sharded_sessions_columns
  override = try(var.overrides["sessions"], {})
}

module "sessions_v" {
  source = "../../lib/view"

  enabled  = local.read && !contains(var.exclude, "sessions_v")
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
  override = try(var.overrides["sessions_v"], {})

  depends_on = [
    module.sessions,
  ]
}
