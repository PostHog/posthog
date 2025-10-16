from posthog.temporal.data_imports.sources.shopify.constants import (
    ABANDONED_CHECKOUTS,
    ARTICLES,
    SHOPIFY_PAYMENTS_ACCOUNT_BALANCE_TRANSACTIONS,
)
from posthog.warehouse.types import IncrementalField, IncrementalFieldType

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    ABANDONED_CHECKOUTS: [
        {
            "label": "createdAt",
            "type": IncrementalFieldType.Timestamp,
            "field": "createdAt",
            "field_type": IncrementalFieldType.Timestamp,
        },
        {
            "label": "completedAt",
            "type": IncrementalFieldType.Timestamp,
            "field": "completedAt",
            "field_type": IncrementalFieldType.Timestamp,
        },
        {
            "label": "updatedAt",
            "type": IncrementalFieldType.Timestamp,
            "field": "updatedAt",
            "field_type": IncrementalFieldType.Timestamp,
        },
    ],
    ARTICLES: [
        {
            "label": "createdAt",
            "type": IncrementalFieldType.Timestamp,
            "field": "createdAt",
            "field_type": IncrementalFieldType.Timestamp,
        },
        {
            "label": "publishedAt",
            "type": IncrementalFieldType.Timestamp,
            "field": "publishedAt",
            "field_type": IncrementalFieldType.Timestamp,
        },
        {
            "label": "updatedAt",
            "type": IncrementalFieldType.Timestamp,
            "field": "updatedAt",
            "field_type": IncrementalFieldType.Timestamp,
        },
    ],
    SHOPIFY_PAYMENTS_ACCOUNT_BALANCE_TRANSACTIONS: [
        {
            "label": "transactionDate",
            "type": IncrementalFieldType.Timestamp,
            "field": "transactionDate",
            "field_type": IncrementalFieldType.Timestamp,
        },
    ],
}
