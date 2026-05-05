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

# Subscriptions list rejects sorting=created_at (Polar's enum is
# customer/status/started_at/current_period_end/ended_at/ends_at/amount/product/discount).
# started_at is set once when the subscription starts and is accepted as a sort key,
# so it works as a monotonic client-side cursor.
_STARTED_AT_INCREMENTAL_FIELD: IncrementalField = {
    "label": "started_at",
    "type": IncrementalFieldType.DateTime,
    "field": "started_at",
    "field_type": IncrementalFieldType.DateTime,
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint: [
        _STARTED_AT_INCREMENTAL_FIELD if endpoint == SUBSCRIPTION_RESOURCE_NAME else _CREATED_AT_INCREMENTAL_FIELD
    ]
    for endpoint in ENDPOINTS
}
