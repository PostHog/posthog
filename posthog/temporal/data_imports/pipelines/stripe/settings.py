"""Stripe analytics source settings and constants"""

# the most popular endpoints
# Full list of the Stripe API endpoints you can find here: https://stripe.com/docs/api.
# These endpoints are converted into ExternalDataSchema objects when a source is linked.

from posthog.warehouse.types import IncrementalField, IncrementalFieldType


ENDPOINTS = ("BalanceTransaction", "Subscription", "Customer", "Product", "Price", "Invoice", "Charge")

INCREMENTAL_ENDPOINTS = ("BalanceTransaction", "Subscription", "Customer", "Product", "Price", "Invoice", "Charge")

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Account": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "BalanceTransaction": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "Subscription": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "Customer": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "Product": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "Price": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "Invoice": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
    "Charge": [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
}
