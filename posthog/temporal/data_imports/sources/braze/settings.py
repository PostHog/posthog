from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "campaigns",
    "campaigns_analytics",
    "canvases",
    "canvases_analytics",
    "events",
    "events_analytics",
    "kpi_daily_new_users",
    "kpi_daily_active_users",
    "kpi_daily_app_uninstalls",
    "cards",
    "cards_analytics",
    "segments",
    "segments_analytics",
)

INCREMENTAL_ENDPOINTS = (
    "campaigns_analytics",
    "canvases_analytics",
    "events_analytics",
    "kpi_daily_new_users",
    "kpi_daily_active_users",
    "kpi_daily_app_uninstalls",
    "cards_analytics",
    "segments_analytics",
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "campaigns_analytics": [
        {
            "label": "time",
            "type": IncrementalFieldType.DateTime,
            "field": "time",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "canvases_analytics": [
        {
            "label": "time",
            "type": IncrementalFieldType.DateTime,
            "field": "time",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "events_analytics": [
        {
            "label": "time",
            "type": IncrementalFieldType.DateTime,
            "field": "time",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "kpi_daily_new_users": [
        {
            "label": "time",
            "type": IncrementalFieldType.DateTime,
            "field": "time",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "kpi_daily_active_users": [
        {
            "label": "time",
            "type": IncrementalFieldType.DateTime,
            "field": "time",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "kpi_daily_app_uninstalls": [
        {
            "label": "time",
            "type": IncrementalFieldType.DateTime,
            "field": "time",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "cards_analytics": [
        {
            "label": "time",
            "type": IncrementalFieldType.DateTime,
            "field": "time",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "segments_analytics": [
        {
            "label": "time",
            "type": IncrementalFieldType.DateTime,
            "field": "time",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
