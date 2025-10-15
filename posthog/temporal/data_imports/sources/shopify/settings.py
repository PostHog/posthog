from posthog.temporal.data_imports.sources.shopify.constants import (
    ABANDONED_CHECKOUTS,
    ARTICLES,
    SHOPIFY_PAYMENTS_BALANCE_TRANSACTIONS,
)
from posthog.warehouse.types import IncrementalField

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    ABANDONED_CHECKOUTS: [
        # {
        #     "label": "created_at",
        #     "type": IncrementalFieldType.DateTime,
        #     "field": "created",
        #     "field_type": IncrementalFieldType.Integer,
        # }
    ],
    ARTICLES: [],
    SHOPIFY_PAYMENTS_BALANCE_TRANSACTIONS: [],
}
