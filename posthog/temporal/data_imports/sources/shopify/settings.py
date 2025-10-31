from dataclasses import dataclass, field

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode
from posthog.temporal.data_imports.sources.shopify.constants import (
    ABANDONED_CHECKOUTS,
    ARTICLES,
    BLOGS,
    CATALOGS,
    COLLECTIONS,
    CREATED_AT,
    CUSTOMERS,
    ID,
    UPDATED_AT,
)
from posthog.warehouse.types import IncrementalField, IncrementalFieldType


# TODO: andrew - pull EndpointConfig out from reddit_ads and into common place. make this extend that class
# to include query_filter for graphql endpoints
@dataclass
class ShopifyEndpointConfig:
    fields: list[IncrementalField]
    query_filter: str | None
    partition_count: int = 1
    partition_size: int = 1
    partition_mode: PartitionMode | None = "datetime"
    partition_format: PartitionFormat | None = "week"
    partition_keys: list[str] = field(default_factory=lambda: [CREATED_AT])


ENDPOINT_CONFIGS: dict[str, ShopifyEndpointConfig] = {
    ABANDONED_CHECKOUTS: ShopifyEndpointConfig(
        fields=[
            {
                "label": "createdAt",
                "type": IncrementalFieldType.Timestamp,
                "field": CREATED_AT,
                "field_type": IncrementalFieldType.Timestamp,
            },
        ],
        query_filter=CREATED_AT,
    ),
    ARTICLES: ShopifyEndpointConfig(
        fields=[
            {
                "label": "updatedAt",
                "type": IncrementalFieldType.Timestamp,
                "field": UPDATED_AT,
                "field_type": IncrementalFieldType.Timestamp,
            },
        ],
        query_filter=UPDATED_AT,
    ),
    BLOGS: ShopifyEndpointConfig(
        fields=[],
        query_filter=None,
        partition_count=200,
        partition_size=1,
        partition_mode="md5",
        partition_format=None,
        partition_keys=[ID],
    ),
    CATALOGS: ShopifyEndpointConfig(
        fields=[],
        query_filter=None,
        partition_count=200,
        partition_size=1,
        partition_mode="md5",
        partition_format=None,
        partition_keys=[ID],
    ),
    COLLECTIONS: ShopifyEndpointConfig(
        fields=[
            {
                "label": "updatedAt",
                "type": IncrementalFieldType.Timestamp,
                "field": UPDATED_AT,
                "field_type": IncrementalFieldType.Timestamp,
            },
        ],
        query_filter=UPDATED_AT,
        partition_count=200,
        partition_size=1,
        partition_mode="md5",
        partition_format=None,
        partition_keys=[ID],
    ),
    CUSTOMERS: ShopifyEndpointConfig(
        fields=[
            {
                "label": "updatedAt",
                "type": IncrementalFieldType.Timestamp,
                "field": UPDATED_AT,
                "field_type": IncrementalFieldType.Timestamp,
            },
        ],
        query_filter=UPDATED_AT,
    ),
}
