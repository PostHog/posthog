# Distributed tables, views and dictionaries that queries read from.


module "raw_sessions_v" {
  source = "../../lib/view"

  enabled  = local.read && !contains(local.deployment.exclude, "raw_sessions_v")
  database = var.database
  name     = "raw_sessions_v"
  query    = <<-SQL
    SELECT
        session_id_v7,
        fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000)) AS session_timestamp,
        team_id,
        argMaxMerge(distinct_id) AS distinct_id,
        min(min_timestamp) AS min_timestamp,
        max(max_timestamp) AS max_timestamp,
        max(max_inserted_at) AS max_inserted_at,
        arrayDistinct(arrayFlatten(groupArray(urls))) AS urls,
        argMinMerge(entry_url) AS entry_url,
        argMaxMerge(end_url) AS end_url,
        argMaxMerge(last_external_click_url) AS last_external_click_url,
        argMinMerge(initial_browser) AS initial_browser,
        argMinMerge(initial_browser_version) AS initial_browser_version,
        argMinMerge(initial_os) AS initial_os,
        argMinMerge(initial_os_version) AS initial_os_version,
        argMinMerge(initial_device_type) AS initial_device_type,
        argMinMerge(initial_viewport_width) AS initial_viewport_width,
        argMinMerge(initial_viewport_height) AS initial_viewport_height,
        argMinMerge(initial_geoip_country_code) AS initial_geoip_country_code,
        argMinMerge(initial_geoip_subdivision_1_code) AS initial_geoip_subdivision_1_code,
        argMinMerge(initial_geoip_subdivision_1_name) AS initial_geoip_subdivision_1_name,
        argMinMerge(initial_geoip_subdivision_city_name) AS initial_geoip_subdivision_city_name,
        argMinMerge(initial_geoip_time_zone) AS initial_geoip_time_zone,
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
        argMinMerge(initial__kx) AS initial__kx,
        argMinMerge(initial_irclid) AS initial_irclid,
        sum(pageview_count) AS pageview_count,
        uniqMerge(pageview_uniq) AS pageview_uniq,
        sum(autocapture_count) AS autocapture_count,
        uniqMerge(autocapture_uniq) AS autocapture_uniq,
        sum(screen_count) AS screen_count,
        uniqMerge(screen_uniq) AS screen_uniq,
        max(maybe_has_session_replay) AS maybe_has_session_replay,
        uniqUpToMerge(1)(page_screen_autocapture_uniq_up_to) AS page_screen_autocapture_uniq_up_to,
        argMinMerge(vitals_lcp) AS vitals_lcp
    FROM ${var.database}.raw_sessions
    GROUP BY
        session_id_v7,
        team_id
  SQL
  override = try(local.deployment.overrides["raw_sessions_v"], {})

  depends_on = [
    module.sharded_raw_sessions_family,
  ]
}


module "raw_sessions_v3_v" {
  source = "../../lib/view"

  enabled  = local.read && !contains(local.deployment.exclude, "raw_sessions_v3_v")
  database = var.database
  name     = "raw_sessions_v3_v"
  query    = <<-SQL
    SELECT
        session_id_v7,
        session_timestamp,
        team_id,
        argMaxMerge(distinct_id) AS distinct_id,
        groupUniqArrayMerge(distinct_ids) AS distinct_ids,
        min(min_timestamp) AS min_timestamp,
        max(max_timestamp) AS max_timestamp,
        max(max_inserted_at) AS max_inserted_at,
        groupUniqArrayArray(2000)(urls) AS urls,
        argMinMerge(entry_url) AS entry_url,
        argMaxMerge(end_url) AS end_url,
        argMaxMerge(last_external_click_url) AS last_external_click_url,
        argMinMerge(browser) AS browser,
        argMinMerge(browser_version) AS browser_version,
        argMinMerge(os) AS os,
        argMinMerge(os_version) AS os_version,
        argMinMerge(device_type) AS device_type,
        argMinMerge(viewport_width) AS viewport_width,
        argMinMerge(viewport_height) AS viewport_height,
        argMinMerge(geoip_country_code) AS geoip_country_code,
        argMinMerge(geoip_subdivision_1_code) AS geoip_subdivision_1_code,
        argMinMerge(geoip_subdivision_1_name) AS geoip_subdivision_1_name,
        argMinMerge(geoip_subdivision_city_name) AS geoip_subdivision_city_name,
        argMinMerge(geoip_time_zone) AS geoip_time_zone,
        argMinMerge(entry_utm_source) AS entry_utm_source,
        argMinMerge(entry_utm_campaign) AS entry_utm_campaign,
        argMinMerge(entry_utm_medium) AS entry_utm_medium,
        argMinMerge(entry_utm_term) AS entry_utm_term,
        argMinMerge(entry_utm_content) AS entry_utm_content,
        argMinMerge(entry_referring_domain) AS entry_referring_domain,
        argMinMerge(entry_gclid) AS entry_gclid,
        argMinMerge(entry_gad_source) AS entry_gad_source,
        argMinMerge(entry_fbclid) AS entry_fbclid,
        argMinMerge(entry_has_gclid) AS entry_has_gclid,
        argMinMerge(entry_has_fbclid) AS entry_has_fbclid,
        argMinMerge(entry_ad_ids_map) AS entry_ad_ids_map,
        argMinMerge(entry_ad_ids_set) AS entry_ad_ids_set,
        argMinMerge(entry_channel_type_properties) AS entry_channel_type_properties,
        uniqExactMerge(pageview_uniq) AS pageview_uniq,
        uniqExactMerge(autocapture_uniq) AS autocapture_uniq,
        uniqExactMerge(screen_uniq) AS screen_uniq,
        uniqUpToMerge(1)(page_screen_uniq_up_to) AS page_screen_uniq_up_to,
        max(has_autocapture) AS has_autocapture,
        groupUniqArrayArray(10000)(flag_key_values) AS flag_key_values,
        groupUniqArrayArray(flag_keys) AS flag_keys,
        groupUniqArrayArray(2000)(event_names) AS event_names,
        groupUniqArrayArray(100)(hosts) AS hosts,
        groupUniqArrayArray(10)(emails) AS emails,
        max(has_replay_events) AS has_replay_events
    FROM ${var.database}.raw_sessions_v3
    GROUP BY
        session_id_v7,
        session_timestamp,
        team_id
  SQL
  override = try(local.deployment.overrides["raw_sessions_v3_v"], {})

  depends_on = [
    module.sharded_raw_sessions_v3_family,
  ]
}
