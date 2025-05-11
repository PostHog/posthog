"""Stripe analytics source settings and constants"""

# the most popular endpoints
# Full list of the Stripe API endpoints you can find here: https://stripe.com/docs/api.
# These endpoints are converted into ExternalDataSchema objects when a source is linked.

from posthog.warehouse.types import IncrementalField, IncrementalFieldType
from posthog.temporal.data_imports.pipelines.stripe.constants import (
    ACCOUNT_RESOURCE_NAME,
    BALANCE_TRANSACTION_RESOURCE_NAME,
    CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
)

ENDPOINTS = (
    BALANCE_TRANSACTION_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    CHARGE_RESOURCE_NAME,
)
INCREMENTAL_ENDPOINTS = (
    BALANCE_TRANSACTION_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    CHARGE_RESOURCE_NAME,
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    ACCOUNT_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    BALANCE_TRANSACTION_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    SUBSCRIPTION_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    CUSTOMER_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    PRODUCT_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    PRICE_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    INVOICE_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    CHARGE_RESOURCE_NAME: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
}
