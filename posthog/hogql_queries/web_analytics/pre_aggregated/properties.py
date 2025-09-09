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
    "metadata.loggedIn": "mat_metadata_loggedIn",
    "metadata.backend": "mat_metadata_backend",
}

ATTRIBUTION_PROPERTIES = {
    "$entry_gclid": "has_gclid",
    "$entry_gad_source": "has_gad_source_paid_search",
    "$entry_fbclid": "has_fbclid",
}

PATH_PROPERTIES = {
    "$entry_pathname": "entry_pathname",
    "$end_pathname": "end_pathname",
}

VIRTUAL_PROPERTIES = {
    # Channel type is a virtual field computed from other session attributes
    # It doesn't map to a single column but needs special handling
    "$channel_type": None,
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

WEB_TRENDS_SPECIFIC_PROPERTIES = {
    "$pathname": "pathname",
}

STATS_TABLE_SUPPORTED_FILTERS = {
    **BASE_SUPPORTED_PROPERTIES,
    **ATTRIBUTION_PROPERTIES,
    **PATH_PROPERTIES,
    **VIRTUAL_PROPERTIES,
    **STATS_TABLE_SPECIFIC_PROPERTIES,
}

WEB_OVERVIEW_SUPPORTED_PROPERTIES = {
    **BASE_SUPPORTED_PROPERTIES,
    **ATTRIBUTION_PROPERTIES,
    **PATH_PROPERTIES,
    **VIRTUAL_PROPERTIES,
    **WEB_OVERVIEW_SPECIFIC_PROPERTIES,
}

EVENT_PROPERTY_TO_FIELD = {
    "$browser": "browser",
    "$os": "os",
    "$viewport_width": "viewport_width",
    "$viewport_height": "viewport_height",
    "$geoip_country_code": "country_code",
    "$geoip_city_name": "city_name",
    "$geoip_subdivision_1_code": "region_code",
    "$geoip_subdivision_1_name": "region_name",
    "utm_source": "utm_source",
    "utm_medium": "utm_medium",
    "utm_campaign": "utm_campaign",
    "utm_term": "utm_term",
    "utm_content": "utm_content",
    "$referring_domain": "referring_domain",
    "metadata.loggedIn": "mat_metadata_loggedIn",
    "metadata.backend": "mat_metadata_backend",
}

SESSION_PROPERTY_TO_FIELD = {
    "$entry_pathname": "entry_pathname",
    "$end_pathname": "end_pathname",
}

WEB_ANALYTICS_TRENDS_SUPPORTED_FILTERS = {
    **BASE_SUPPORTED_PROPERTIES,
    **ATTRIBUTION_PROPERTIES,
    **PATH_PROPERTIES,
    **VIRTUAL_PROPERTIES,
    **WEB_TRENDS_SPECIFIC_PROPERTIES,
}
