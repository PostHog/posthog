from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

# Endpoints to sync from Mailchimp Marketing API v3
# Based on Airbyte and Fivetran implementations
ENDPOINTS = (
    "lists",
    "campaigns",
    "automations",
    "reports",
)

# Incremental fields for each endpoint
# Most Mailchimp endpoints support date-based filtering
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "campaigns": [
        {
            "label": "send_time",
            "type": IncrementalFieldType.DateTime,
            "field": "send_time",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "reports": [
        {
            "label": "send_time",
            "type": IncrementalFieldType.DateTime,
            "field": "send_time",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
