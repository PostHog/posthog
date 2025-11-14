from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

# Standard Google Analytics 4 reports
# These are pre-defined reports based on common GA4 dimensions and metrics
ENDPOINTS = [
    "daily_active_users",
    "weekly_active_users",
    "devices",
    "locations",
    "pages",
    "traffic_sources",
    "sessions",
    "events",
    "conversions",
    "user_acquisition",
    "traffic_acquisition",
    "engagement",
]

# Incremental fields for GA4 reports
# Most GA4 reports can be synced incrementally by date
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "daily_active_users": [
        {"label": "Date", "type": IncrementalFieldType.Date, "field": "date", "field_type": IncrementalFieldType.Date}
    ],
    "weekly_active_users": [
        {"label": "Date", "type": IncrementalFieldType.Date, "field": "date", "field_type": IncrementalFieldType.Date}
    ],
    "devices": [
        {"label": "Date", "type": IncrementalFieldType.Date, "field": "date", "field_type": IncrementalFieldType.Date}
    ],
    "locations": [
        {"label": "Date", "type": IncrementalFieldType.Date, "field": "date", "field_type": IncrementalFieldType.Date}
    ],
    "pages": [
        {"label": "Date", "type": IncrementalFieldType.Date, "field": "date", "field_type": IncrementalFieldType.Date}
    ],
    "traffic_sources": [
        {"label": "Date", "type": IncrementalFieldType.Date, "field": "date", "field_type": IncrementalFieldType.Date}
    ],
    "sessions": [
        {"label": "Date", "type": IncrementalFieldType.Date, "field": "date", "field_type": IncrementalFieldType.Date}
    ],
    "events": [
        {"label": "Date", "type": IncrementalFieldType.Date, "field": "date", "field_type": IncrementalFieldType.Date}
    ],
    "conversions": [
        {"label": "Date", "type": IncrementalFieldType.Date, "field": "date", "field_type": IncrementalFieldType.Date}
    ],
    "user_acquisition": [
        {"label": "Date", "type": IncrementalFieldType.Date, "field": "date", "field_type": IncrementalFieldType.Date}
    ],
    "traffic_acquisition": [
        {"label": "Date", "type": IncrementalFieldType.Date, "field": "date", "field_type": IncrementalFieldType.Date}
    ],
    "engagement": [
        {"label": "Date", "type": IncrementalFieldType.Date, "field": "date", "field_type": IncrementalFieldType.Date}
    ],
}
