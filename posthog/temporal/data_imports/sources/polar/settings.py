"""Polar.sh data warehouse source settings and constants"""

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

# Core Polar.sh API endpoints
# Full API documentation: https://docs.polar.sh/api-reference

ORDERS_RESOURCE_NAME = "orders"
SUBSCRIPTIONS_RESOURCE_NAME = "subscriptions"
PRODUCTS_RESOURCE_NAME = "products"
CUSTOMERS_RESOURCE_NAME = "customers"
BENEFITS_RESOURCE_NAME = "benefits"
CHECKOUTS_RESOURCE_NAME = "checkouts"
TRANSACTIONS_RESOURCE_NAME = "transactions"

# Endpoints available for import
ENDPOINTS = (
    ORDERS_RESOURCE_NAME,
    SUBSCRIPTIONS_RESOURCE_NAME,
    PRODUCTS_RESOURCE_NAME,
    CUSTOMERS_RESOURCE_NAME,
    BENEFITS_RESOURCE_NAME,
    CHECKOUTS_RESOURCE_NAME,
    TRANSACTIONS_RESOURCE_NAME,
)

# Incremental fields for each endpoint
# Using created_at as the partition key since it's stable and doesn't change
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    ORDERS_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    SUBSCRIPTIONS_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    PRODUCTS_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    CUSTOMERS_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    BENEFITS_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    CHECKOUTS_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    TRANSACTIONS_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
