from posthog.temporal.data_imports.sources.polar.constants import (
    BENEFIT_RESOURCE_NAME,
    CHECKOUT_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    ORDER_RESOURCE_NAME,
    ORGANIZATION_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    REFUND_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
)

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = [
    CUSTOMER_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    ORDER_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    REFUND_RESOURCE_NAME,
    CHECKOUT_RESOURCE_NAME,
    BENEFIT_RESOURCE_NAME,
    ORGANIZATION_RESOURCE_NAME,
]

_CREATED_AT_INCREMENTAL_FIELD: IncrementalField = {
    "label": "created_at",
    "type": IncrementalFieldType.DateTime,
    "field": "created_at",
    "field_type": IncrementalFieldType.DateTime,
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint: [_CREATED_AT_INCREMENTAL_FIELD] for endpoint in ENDPOINTS
}
