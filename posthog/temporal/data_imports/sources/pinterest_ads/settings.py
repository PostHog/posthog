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

# Pinterest Ads API v5 analytics columns
# Full column reference: https://developers.pinterest.com/docs/api/v5/ads-analytics/
ANALYTICS_COLUMNS = [
    # Spend
    "SPEND_IN_DOLLAR",  # Total ad spend in dollars
    "SPEND_IN_MICRO_DOLLAR",  # Total ad spend in micro-dollars (1/1,000,000 of a dollar)
    # Impressions
    "PAID_IMPRESSION",  # Paid impressions
    "IMPRESSION_1",  # Total paid + earned impressions
    "IMPRESSION_2",  # Earned impressions only
    "TOTAL_IMPRESSION",  # Total impressions across all types
    # Clicks
    "CLICKTHROUGH_1",  # Total paid + earned clicks
    "CLICKTHROUGH_2",  # Earned clicks only
    "TOTAL_CLICKTHROUGH",  # Total clicks across all types
    "OUTBOUND_CLICK_1",  # Clicks leaving Pinterest to external URL
    # Engagement
    "TOTAL_ENGAGEMENT",  # Total engagements (clicks, saves, closeups, etc.)
    "ENGAGEMENT_1",  # Total paid + earned engagements
    "ENGAGEMENT_2",  # Earned engagements only
    "ENGAGEMENT_RATE",  # Engagements / impressions
    "EENGAGEMENT_RATE",  # Effective engagement rate including earned
    "REPIN_RATE",  # Save rate (saves / impressions)
    # Rates
    "CTR",  # Click-through rate (clicks / impressions)
    "ECTR",  # Effective CTR including earned
    "CTR_2",  # Earned CTR
    "OUTBOUND_CTR_1",  # Outbound CTR (clicks leaving Pinterest / impressions)
    # Cost metrics
    "CPC_IN_MICRO_DOLLAR",  # Cost per click in micro-dollars
    "ECPC_IN_MICRO_DOLLAR",  # Effective cost per click in micro-dollars
    "ECPC_IN_DOLLAR",  # Effective cost per click in dollars
    "ECPM_IN_MICRO_DOLLAR",  # Effective cost per 1000 impressions in micro-dollars
    "CPM_IN_MICRO_DOLLAR",  # Cost per 1000 impressions in micro-dollars
    "CPM_IN_DOLLAR",  # Cost per 1000 impressions in dollars
    "ECPE_IN_DOLLAR",  # Effective cost per engagement in dollars
    # Conversions
    "TOTAL_CONVERSIONS",  # Total conversions across all types
    "TOTAL_CHECKOUT",  # Total checkout conversions
    "TOTAL_CHECKOUT_VALUE_IN_MICRO_DOLLAR",  # Total value of checkouts in micro-dollars
    "CHECKOUT_ROAS",  # Return on ad spend for checkouts
    "TOTAL_SIGNUP",  # Total signup conversions
    "TOTAL_LEAD",  # Total lead conversions
    "TOTAL_PAGE_VISIT",  # Total page visit conversions
    # Video
    "TOTAL_VIDEO_3SEC_VIEWS",  # 3-second video views
    "TOTAL_VIDEO_MRC_VIEWS",  # MRC standard video views (2sec+ and 50%+ visible)
    "TOTAL_VIDEO_AVG_WATCHTIME_IN_SECOND",  # Average video watch time in seconds
    "TOTAL_VIDEO_P100_COMPLETE",  # Video watched to 100%
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
