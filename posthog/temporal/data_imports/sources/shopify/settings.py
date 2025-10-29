from dataclasses import dataclass

from posthog.temporal.data_imports.sources.shopify.constants import ABANDONED_CHECKOUTS, ARTICLES

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


# TODO: andrew - pull EndpointConfig out from reddit_ads and into common place. make this extend that class
# to include query_filter for graphql endpoints
@dataclass
class ShopifyIncrementalSetting:
    fields: list[IncrementalField]
    query_filter: str
    partition_keys: list[str]


CREATED_AT = "created_at"
UPDATED_AT = "updated_at"

INCREMENTAL_SETTINGS: dict[str, ShopifyIncrementalSetting] = {
    ABANDONED_CHECKOUTS: ShopifyIncrementalSetting(
        fields=[
            {
                "label": "createdAt",
                "type": IncrementalFieldType.Timestamp,
                "field": CREATED_AT,
                "field_type": IncrementalFieldType.Timestamp,
            },
        ],
        query_filter=CREATED_AT,
        partition_keys=[CREATED_AT],
    ),
    ARTICLES: ShopifyIncrementalSetting(
        fields=[
            {
                "label": "updatedAt",
                "type": IncrementalFieldType.Timestamp,
                "field": UPDATED_AT,
                "field_type": IncrementalFieldType.Timestamp,
            },
        ],
        query_filter=UPDATED_AT,
        partition_keys=[CREATED_AT],
    ),
}
