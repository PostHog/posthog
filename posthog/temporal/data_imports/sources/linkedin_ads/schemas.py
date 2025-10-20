from enum import StrEnum
from typing import Literal, NotRequired, TypedDict

from posthog.warehouse.types import IncrementalFieldType

FLOAT_FIELDS = {"costInUsd"}

# There are in the results from the API. The value is in the URN format.
URN_COLUMNS = ["campaignGroup", "account", "campaign", "creative"]

# This maps the the URN type to the virtual column name. LinkedIn Ads API uses URNs to identify resources.
# URNs are like "urn:li:sponsoredCampaign:12345678"
VIRTUAL_COLUMN_URN_MAPPING = {
    "sponsoredCampaign": "campaign_id",
    "sponsoredCampaignGroup": "campaign_group_id",
    "sponsoredAccount": "account_id",
    "sponsoredCreative": "creative_id",
}


class LinkedinAdsResource(StrEnum):
    Accounts = "accounts"
    Campaigns = "campaigns"
    CampaignGroups = "campaign_groups"
    CampaignStats = "campaign_stats"
    CampaignGroupStats = "campaign_group_stats"


class LinkedinAdsPivot(StrEnum):
    ACCOUNT = "ACCOUNT"
    CAMPAIGN = "CAMPAIGN"
    CAMPAIGN_GROUP = "CAMPAIGN_GROUP"
    CREATIVE = "CREATIVE"


# LinkedIn API endpoint mappings
LINKEDIN_ADS_ENDPOINTS = {
    LinkedinAdsResource.Accounts: "adAccounts",
    LinkedinAdsResource.Campaigns: "adCampaigns",
    LinkedinAdsResource.CampaignGroups: "adCampaignGroups",
    LinkedinAdsResource.CampaignStats: "adAnalytics",
    LinkedinAdsResource.CampaignGroupStats: "adAnalytics",
}

# Pivot mappings for analytics resources
LINKEDIN_ADS_PIVOTS = {
    LinkedinAdsResource.CampaignStats: LinkedinAdsPivot.CAMPAIGN,
    LinkedinAdsResource.CampaignGroupStats: LinkedinAdsPivot.CAMPAIGN_GROUP,
}


class ResourceSchema(TypedDict):
    resource_name: str
    field_names: list[str]
    primary_key: list[str]
    filter_field_names: NotRequired[list[tuple[str, IncrementalFieldType]]]
    partition_keys: list[str]
    partition_mode: Literal["md5", "numerical", "datetime"] | None
    partition_format: Literal["month", "day"] | None
    partition_size: int
    is_stats: bool


# LinkedIn Ads resource schemas
RESOURCE_SCHEMAS: dict[LinkedinAdsResource, ResourceSchema] = {
    LinkedinAdsResource.Accounts: {
        "resource_name": "accounts",
        "field_names": ["id", "name", "status", "type", "currency", "version"],
        "primary_key": ["id"],
        "partition_keys": ["id"],
        "partition_mode": "numerical",
        "partition_format": None,
        "is_stats": False,
        "partition_size": 1000,
    },
    LinkedinAdsResource.Campaigns: {
        "resource_name": "campaigns",
        "field_names": [
            "id",
            "name",
            "account",
            "campaignGroup",
            "status",
            "type",
            "changeAuditStamps",
            "runSchedule",
            "dailyBudget",
            "unitCost",
            "costType",
            "targetingCriteria",
            "locale",
            "version",
        ],
        "primary_key": ["id"],
        "partition_keys": ["created_time"],
        "partition_mode": "datetime",
        "partition_format": "month",
        "is_stats": False,
        "partition_size": 1,
    },
    LinkedinAdsResource.CampaignGroups: {
        "resource_name": "campaign_groups",
        "field_names": [
            "id",
            "name",
            "account",
            "status",
            "runSchedule",
            "totalBudget",
            "changeAuditStamps",
        ],
        "primary_key": ["id"],
        "partition_keys": ["created_time"],
        "partition_mode": "datetime",
        "partition_format": "month",
        "is_stats": False,
        "partition_size": 1,
    },
    LinkedinAdsResource.CampaignStats: {
        "resource_name": "campaign_stats",
        "field_names": [
            "impressions",
            "clicks",
            "dateRange",
            "pivotValues",
            "costInUsd",
            "externalWebsiteConversions",
            "landingPageClicks",
            "totalEngagements",
            "videoViews",
            "videoCompletions",
            "oneClickLeads",
            "follows",
        ],
        "primary_key": ["date_start", "date_end", "campaign_id"],
        "filter_field_names": [
            ("date_start", IncrementalFieldType.Date),
        ],
        "partition_keys": ["date_start"],
        "partition_mode": "datetime",
        "partition_format": "month",
        "is_stats": True,
        "partition_size": 1,
    },
    LinkedinAdsResource.CampaignGroupStats: {
        "resource_name": "campaign_group_stats",
        "field_names": [
            "impressions",
            "clicks",
            "dateRange",
            "pivotValues",
            "costInUsd",
            "externalWebsiteConversions",
            "landingPageClicks",
            "totalEngagements",
            "videoViews",
            "videoCompletions",
            "oneClickLeads",
            "follows",
        ],
        "primary_key": ["date_start", "date_end", "campaign_group_id"],
        "filter_field_names": [
            ("date_start", IncrementalFieldType.Date),
        ],
        "partition_keys": ["date_start"],
        "partition_mode": "datetime",
        "partition_format": "month",
        "is_stats": True,
        "partition_size": 1,
    },
}
