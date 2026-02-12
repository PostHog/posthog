from dataclasses import dataclass
from enum import Enum
from typing import Optional

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.pinterest.com/v5"
PAGE_SIZE = 250
ANALYTICS_MAX_IDS = 250
ANALYTICS_MAX_DATE_RANGE_DAYS = 90
DEFAULT_LOOKBACK_DAYS = 89

ANALYTICS_COLUMNS = [
    "SPEND_IN_DOLLAR",
    "SPEND_IN_MICRO_DOLLAR",
    "PAID_IMPRESSION",
    "TOTAL_CLICKTHROUGH",
    "TOTAL_ENGAGEMENT",
    "CTR",
    "TOTAL_CONVERSIONS",
    "TOTAL_CHECKOUT",
    "TOTAL_CHECKOUT_VALUE_IN_MICRO_DOLLAR",
    "VIDEO_3SEC_VIEWS_1",
    "CPC_IN_MICRO_DOLLAR",
    "ECPM_IN_DOLLAR",
]


class EndpointType(str, Enum):
    ENTITY = "entity"
    ANALYTICS = "analytics"


@dataclass
class EndpointConfig:
    name: str
    primary_keys: list[str]
    partition_keys: list[str]
    partition_mode: PartitionMode
    endpoint_type: EndpointType
    incremental_fields: Optional[list[IncrementalField]] = None
    partition_format: Optional[PartitionFormat] = None
    partition_size: int = 1


PINTEREST_ADS_CONFIG: dict[str, EndpointConfig] = {
    "campaigns": EndpointConfig(
        name="campaigns",
        primary_keys=["id"],
        incremental_fields=None,
        partition_keys=["created_time"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.ENTITY,
    ),
    "ad_groups": EndpointConfig(
        name="ad_groups",
        primary_keys=["id"],
        incremental_fields=None,
        partition_keys=["created_time"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.ENTITY,
    ),
    "ads": EndpointConfig(
        name="ads",
        primary_keys=["id"],
        incremental_fields=None,
        partition_keys=["created_time"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.ENTITY,
    ),
    "campaign_analytics": EndpointConfig(
        name="campaign_analytics",
        primary_keys=["campaign_id", "date"],
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.ANALYTICS,
    ),
    "ad_group_analytics": EndpointConfig(
        name="ad_group_analytics",
        primary_keys=["ad_group_id", "date"],
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.ANALYTICS,
    ),
    "ad_analytics": EndpointConfig(
        name="ad_analytics",
        primary_keys=["ad_id", "date"],
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="week",
        endpoint_type=EndpointType.ANALYTICS,
    ),
}

ENTITY_ENDPOINT_PATHS: dict[str, str] = {
    "campaigns": "/ad_accounts/{ad_account_id}/campaigns",
    "ad_groups": "/ad_accounts/{ad_account_id}/ad_groups",
    "ads": "/ad_accounts/{ad_account_id}/ads",
}

ANALYTICS_ENDPOINT_PATHS: dict[str, str] = {
    "campaign_analytics": "/ad_accounts/{ad_account_id}/campaigns/analytics",
    "ad_group_analytics": "/ad_accounts/{ad_account_id}/ad_groups/analytics",
    "ad_analytics": "/ad_accounts/{ad_account_id}/ads/analytics",
}

ANALYTICS_ID_PARAM_NAMES: dict[str, str] = {
    "campaign_analytics": "campaign_ids",
    "ad_group_analytics": "ad_group_ids",
    "ad_analytics": "ad_ids",
}

ANALYTICS_ENTITY_SOURCES: dict[str, str] = {
    "campaign_analytics": "campaigns",
    "ad_group_analytics": "ad_groups",
    "ad_analytics": "ads",
}
