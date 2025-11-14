# AppsFlyer Pull API V2 endpoints
# Documentation: https://support.appsflyer.com/hc/en-us/articles/207034346-Pull-API

# Raw data report endpoints
RAW_DATA_ENDPOINTS = [
    "installs_report",
    "in_app_events_report",
    "organic_installs_report",
    "uninstall_events_report",
    "reinstall_events_report",
]

# Aggregate report endpoints
AGGREGATE_ENDPOINTS = [
    "partners_report",
    "partners_by_date_report",
    "geo_by_date_report",
    "daily_report",
]

# Retargeting endpoints
RETARGETING_ENDPOINTS = [
    "retargeting_conversion_events_report",
    "retargeting_in_app_events_report",
]

# All available endpoints
ENDPOINTS = RAW_DATA_ENDPOINTS + AGGREGATE_ENDPOINTS + RETARGETING_ENDPOINTS

# Incremental fields for each endpoint
# Raw data reports use event_time for incremental syncing
# Aggregate reports use the date parameter for incremental syncing
INCREMENTAL_FIELDS: dict[str, list[str]] = {
    # Raw data reports
    "installs_report": ["event_time"],
    "in_app_events_report": ["event_time"],
    "organic_installs_report": ["event_time"],
    "uninstall_events_report": ["event_time"],
    "reinstall_events_report": ["event_time"],
    "retargeting_conversion_events_report": ["event_time"],
    "retargeting_in_app_events_report": ["event_time"],
    # Aggregate reports use date range parameters
    "partners_report": ["date"],
    "partners_by_date_report": ["date"],
    "geo_by_date_report": ["date"],
    "daily_report": ["date"],
}

# Partition fields - using event_time for raw data (stable field that doesn't change)
# For aggregate reports, we use date
PARTITION_FIELDS: dict[str, str] = {
    "installs_report": "event_time",
    "in_app_events_report": "event_time",
    "organic_installs_report": "event_time",
    "uninstall_events_report": "event_time",
    "reinstall_events_report": "event_time",
    "retargeting_conversion_events_report": "event_time",
    "retargeting_in_app_events_report": "event_time",
    "partners_report": "date",
    "partners_by_date_report": "date",
    "geo_by_date_report": "date",
    "daily_report": "date",
}
