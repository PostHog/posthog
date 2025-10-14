from posthog.temporal.data_imports.sources.shopify.constants import (
    ABANDONED_CHECKOUTS_RESOURCE_NAME,
    ARTICLES_RESOURCE_NAME,
    SHOPIFY_PAYMENTS_BALANCE_TRANSACTIONS_RESOURCE_NAME,
)
from posthog.warehouse.types import IncrementalField

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    ABANDONED_CHECKOUTS_RESOURCE_NAME: [
        # {
        #     "label": "created_at",
        #     "type": IncrementalFieldType.DateTime,
        #     "field": "created",
        #     "field_type": IncrementalFieldType.Integer,
        # }
    ],
    ARTICLES_RESOURCE_NAME: [],
    SHOPIFY_PAYMENTS_BALANCE_TRANSACTIONS_RESOURCE_NAME: [],
}
