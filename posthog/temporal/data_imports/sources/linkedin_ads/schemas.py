from enum import StrEnum
from typing import Literal, NotRequired, TypedDict

from products.data_warehouse.backend.types import IncrementalFieldType

FLOAT_FIELDS = {"costInUsd", "costInLocalCurrency", "conversionValueInLocalCurrency"}

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
    Creatives = "creatives"
    CampaignStats = "campaign_stats"
    CampaignGroupStats = "campaign_group_stats"
    CreativeStats = "creative_stats"


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
    LinkedinAdsResource.Creatives: "creatives",
    LinkedinAdsResource.CampaignStats: "adAnalytics",
    LinkedinAdsResource.CampaignGroupStats: "adAnalytics",
    LinkedinAdsResource.CreativeStats: "adAnalytics",
}

# Pivot mappings for analytics resources
LINKEDIN_ADS_PIVOTS = {
    LinkedinAdsResource.CampaignStats: LinkedinAdsPivot.CAMPAIGN,
    LinkedinAdsResource.CampaignGroupStats: LinkedinAdsPivot.CAMPAIGN_GROUP,
    LinkedinAdsResource.CreativeStats: LinkedinAdsPivot.CREATIVE,
}


class ResourceSchema(TypedDict):
    resource_name: str
    field_names: list[str]
    primary_key: list[str]
    filter_field_names: NotRequired[list[tuple[str, IncrementalFieldType]]]
    partition_keys: list[str]
    partition_mode: Literal["md5", "numerical", "datetime"] | None
    partition_format: Literal["month", "week", "day"] | None
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
        "partition_format": "week",
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
        "partition_format": "week",
        "is_stats": False,
        "partition_size": 1,
    },
    LinkedinAdsResource.Creatives: {
        "resource_name": "creatives",
        # CreativeV11 differs from the legacy Creative schema — no `type`
        # (creative type is implied by the polymorphic `content` union, which we
        # don't project to keep the response cheap) and no `changeAuditStamps`
        # envelope. Timestamps come as bare longs (`createdAt`, `lastModifiedAt`)
        # which the flattener normalizes into `created_time` / `last_modified_time`
        # virtual columns. `name` exists and is human-readable for most creatives.
        "field_names": [
            "id",
            "account",
            "campaign",
            "name",
            "intendedStatus",
            "isServing",
            "review",
            "createdAt",
            "lastModifiedAt",
        ],
        "primary_key": ["id"],
        "partition_keys": ["created_time"],
        "partition_mode": "datetime",
        "partition_format": "week",
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
            "costInLocalCurrency",
            "externalWebsiteConversions",
            "conversionValueInLocalCurrency",
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
        "partition_format": "week",
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
            "costInLocalCurrency",
            "externalWebsiteConversions",
            "conversionValueInLocalCurrency",
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
        "partition_format": "week",
        "is_stats": True,
        "partition_size": 1,
    },
    LinkedinAdsResource.CreativeStats: {
        "resource_name": "creative_stats",
        # Same metric set as CampaignStats / CampaignGroupStats — LinkedIn's analytics
        # endpoint returns a uniform schema regardless of pivot. The `creative_id`
        # virtual column is derived from `pivotValues` (URN of the creative).
        "field_names": [
            "impressions",
            "clicks",
            "dateRange",
            "pivotValues",
            "costInUsd",
            "costInLocalCurrency",
            "externalWebsiteConversions",
            "conversionValueInLocalCurrency",
            "landingPageClicks",
            "totalEngagements",
            "videoViews",
            "videoCompletions",
            "oneClickLeads",
            "follows",
        ],
        "primary_key": ["date_start", "date_end", "creative_id"],
        "filter_field_names": [
            ("date_start", IncrementalFieldType.Date),
        ],
        "partition_keys": ["date_start"],
        "partition_mode": "datetime",
        "partition_format": "week",
        "is_stats": True,
        "partition_size": 1,
    },
}
