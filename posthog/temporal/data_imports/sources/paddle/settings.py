from posthog.temporal.data_imports.sources.paddle.constants import (
    ADJUSTMENT_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    DISCOUNT_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    TRANSACTION_RESOURCE_NAME,
)

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = [
    CUSTOMER_RESOURCE_NAME,
    DISCOUNT_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    TRANSACTION_RESOURCE_NAME,
    ADJUSTMENT_RESOURCE_NAME,
]

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    TRANSACTION_RESOURCE_NAME: [
        {
            "label": "billed_at",
            "type": IncrementalFieldType.DateTime,
            "field": "billed_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
