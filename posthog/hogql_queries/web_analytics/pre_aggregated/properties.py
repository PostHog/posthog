BASE_SUPPORTED_PROPERTIES = {
    "$host": "host",
    "$device_type": "device_type",
    "$browser": "browser",
    "$browser_version": "browser_version",
    "$os": "os",
    "$os_version": "os_version",
    "$referring_domain": "referring_domain",
    "$entry_utm_source": "utm_source",
    "$entry_utm_medium": "utm_medium",
    "$entry_utm_campaign": "utm_campaign",
    "$entry_utm_term": "utm_term",
    "$entry_utm_content": "utm_content",
    "$geoip_country_code": "country_code",
    "$geoip_country_name": "country_name",
    "$geoip_city_name": "city_name",
    "$geoip_subdivision_1_code": "region_code",
    "$geoip_subdivision_1_name": "region_name",
    "$geoip_time_zone": "time_zone",
}

ATTRIBUTION_PROPERTIES = {
    "$entry_gclid": "gclid",
    "$entry_gad_source": "gad_source",
    "$entry_gclsrc": "gclsrc",
    "$entry_dclid": "dclid",
    "$entry_gbraid": "gbraid",
    "$entry_wbraid": "wbraid",
    "$entry_fbclid": "fbclid",
    "$entry_msclkid": "msclkid",
    "$entry_twclid": "twclid",
    "$entry_li_fat_id": "li_fat_id",
    "$entry_mc_cid": "mc_cid",
    "$entry_igshid": "igshid",
    "$entry_ttclid": "ttclid",
    "$entry_epik": "epik",
    "$entry_qclid": "qclid",
    "$entry_sccid": "sccid",
    "$entry__kx": "_kx",
    "$entry_irclid": "irclid",
}

PATH_PROPERTIES = {
    "$entry_pathname": "entry_pathname",
    "$end_pathname": "end_pathname",
}

STATS_TABLE_SPECIFIC_PROPERTIES = {
    "$pathname": "pathname",
}

# Web overview specific properties (pathname maps to entry_pathname for overview)
WEB_OVERVIEW_SPECIFIC_PROPERTIES = {
    # We convert the pathname to entry_pathname when filtering by pathname for the overview only.
    # This is the same workaround as the one used in the stats_table.py (see _event_properties_for_bounce_rate)
    # The actual way to keep 100% accuracy with the existing version is to join with web_stats_daily
    # and filter by pathname there. This is a compromise to keep the query simpler in the meantime as we
    # don't have access to all events to filter the inner query here.
    "$pathname": "entry_pathname",
}

STATS_TABLE_SUPPORTED_FILTERS = {
    **BASE_SUPPORTED_PROPERTIES,
    **ATTRIBUTION_PROPERTIES,
    **PATH_PROPERTIES,
    **STATS_TABLE_SPECIFIC_PROPERTIES,
}

WEB_OVERVIEW_SUPPORTED_PROPERTIES = {
    **BASE_SUPPORTED_PROPERTIES,
    **ATTRIBUTION_PROPERTIES,
    **PATH_PROPERTIES,
    **WEB_OVERVIEW_SPECIFIC_PROPERTIES,
}
