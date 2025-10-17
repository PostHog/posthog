from dataclasses import dataclass

from posthog.temporal.data_imports.sources.shopify.constants import ABANDONED_CHECKOUTS, ARTICLES
from posthog.warehouse.types import IncrementalField, IncrementalFieldType


@dataclass
class ShopifyIncrementalSetting:
    fields: list[IncrementalField]
    query_filter: str


CREATED_AT = "created_at"
UPDATED_AT = "updated_at"

INCREMENTAL_SETTINGS: dict[str, ShopifyIncrementalSetting] = {
    ABANDONED_CHECKOUTS: ShopifyIncrementalSetting(
        fields=[
            {
                "label": "createdAt",
                "type": IncrementalFieldType.Timestamp,
                "field": "createdAt",
                "field_type": IncrementalFieldType.Timestamp,
            },
        ],
        query_filter=CREATED_AT,
    ),
    ARTICLES: ShopifyIncrementalSetting(
        fields=[
            {
                "label": "updatedAt",
                "type": IncrementalFieldType.Timestamp,
                "field": "updatedAt",
                "field_type": IncrementalFieldType.Timestamp,
            },
        ],
        query_filter=UPDATED_AT,
    ),
}
