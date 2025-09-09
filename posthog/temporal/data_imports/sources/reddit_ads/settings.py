from posthog.warehouse.types import IncrementalField, IncrementalFieldType

REDDIT_ADS_ENDPOINTS = ["campaigns", "ad_groups", "ads", "campaign_metrics", "ad_group_metrics", "ad_metrics"]

REDDIT_ADS_INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "campaigns": [
        {
            "label": "modified_at",
            "type": IncrementalFieldType.DateTime,
            "field": "modified_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "ad_groups": [
        {
            "label": "modified_at",
            "type": IncrementalFieldType.DateTime,
            "field": "modified_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "ads": [
        {
            "label": "modified_at",
            "type": IncrementalFieldType.DateTime,
            "field": "modified_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "campaign_metrics": [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        }
    ],
    "ad_group_metrics": [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        }
    ],
    "ad_metrics": [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        }
    ],
}
