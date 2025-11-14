"""Customer.io source settings and constants"""

from posthog.temporal.data_imports.sources.customer_io.constants import (
    ACTIVITIES_RESOURCE_NAME,
    CAMPAIGNS_RESOURCE_NAME,
    NEWSLETTERS_RESOURCE_NAME,
)

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

# API base URLs for different regions
US_API_BASE_URL = "https://api.customer.io/v1"
EU_API_BASE_URL = "https://api-eu.customer.io/v1"

# Available endpoints to sync
ENDPOINTS = (
    CAMPAIGNS_RESOURCE_NAME,
    NEWSLETTERS_RESOURCE_NAME,
    ACTIVITIES_RESOURCE_NAME,
)

# Incremental sync configuration for each endpoint
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    CAMPAIGNS_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    NEWSLETTERS_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    ACTIVITIES_RESOURCE_NAME: [
        {
            "label": "timestamp",
            "type": IncrementalFieldType.DateTime,
            "field": "timestamp",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
}
