from enum import StrEnum
from typing import NotRequired, TypedDict

from posthog.warehouse.types import IncrementalFieldType

# Field type mappings for data type conversion
INTEGER_FIELDS = {
    "id",
    "campaign_id",
    "campaign_group_id",
    "impressions",
    "clicks",
    "externalWebsiteConversions",
    "landingPageClicks",
    "totalEngagements",
    "videoViews",
    "videoCompletions",
    "oneClickLeads",
    "follows",
}
FLOAT_FIELDS = {"costInUsd"}
DATE_FIELDS = {"dateRange.start"}

# Virtual column mappings for analytics resources
VIRTUAL_COLUMNS = {"campaign_id", "campaign_group_id"}

# This maps the virtual column name to the URN type. LinkedIn Ads API uses URNs to identify resources.
# URNs are like "urn:li:sponsoredCampaign:185129613"
VIRTUAL_COLUMN_URN_MAPPING = {"campaign_id": "Campaign", "campaign_group_id": "CampaignGroup"}
RESOURCE_VIRTUAL_COLUMNS = {"campaign_stats": "campaign_id", "campaign_group_stats": "campaign_group_id"}


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


# LinkedIn Ads resource schemas
RESOURCE_SCHEMAS: dict[LinkedinAdsResource, ResourceSchema] = {
    LinkedinAdsResource.Accounts: {
        "resource_name": "accounts",
        "field_names": ["id", "name", "status", "type", "currency", "version"],
        "primary_key": ["id"],
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
        "primary_key": ["dateRange", "pivotValues"],
        "filter_field_names": [
            ("dateRange.start", IncrementalFieldType.Date),
        ],
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
        "primary_key": ["dateRange", "pivotValues"],
        "filter_field_names": [
            ("dateRange.start", IncrementalFieldType.Date),
        ],
    },
}
