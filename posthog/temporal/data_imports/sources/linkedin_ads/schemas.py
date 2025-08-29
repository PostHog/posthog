from enum import StrEnum

from posthog.warehouse.types import IncrementalField, IncrementalFieldType


class LinkedinAdsResource(StrEnum):
    """LinkedIn Ads API resources we can import"""
    Accounts = "accounts"
    Campaigns = "campaigns"
    CampaignGroups = "campaign_groups"
    CampaignStats = "campaign_stats"
    CampaignGroupStats = "campaign_group_stats"


ENDPOINTS = (
    LinkedinAdsResource.Accounts,
    LinkedinAdsResource.Campaigns,
    LinkedinAdsResource.CampaignGroups,
    LinkedinAdsResource.CampaignStats,
    LinkedinAdsResource.CampaignGroupStats,
)

INCREMENTAL_ENDPOINTS = (
    LinkedinAdsResource.CampaignStats,
    LinkedinAdsResource.CampaignGroupStats,
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    LinkedinAdsResource.CampaignStats: [
        {
            "label": "dateRange.start",
            "type": IncrementalFieldType.Date,
            "field": "dateRange.start",
            "field_type": IncrementalFieldType.Date,
        }
    ],
    LinkedinAdsResource.CampaignGroupStats: [
        {
            "label": "dateRange.start",
            "type": IncrementalFieldType.Date,
            "field": "dateRange.start",
            "field_type": IncrementalFieldType.Date,
        }
    ],
}

# LinkedIn Ads API endpoint mappings
LINKEDIN_ADS_ENDPOINTS = {
    LinkedinAdsResource.Accounts: "adAccounts",
    LinkedinAdsResource.Campaigns: "adCampaigns",
    LinkedinAdsResource.CampaignGroups: "adCampaignGroups",
    LinkedinAdsResource.CampaignStats: "adAnalytics",
    LinkedinAdsResource.CampaignGroupStats: "adAnalytics",
}

# Fields to retrieve for each resource
LINKEDIN_ADS_FIELDS = {
    LinkedinAdsResource.Accounts: [
        "id",
        "name",
        "status",
        "type",
        "currency",
        "version",
    ],
    LinkedinAdsResource.Campaigns: [
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
    LinkedinAdsResource.CampaignGroups: [
        "id",
        "name",
        "account",
        "status",
        "runSchedule",
        "totalBudget",
        "changeAuditStamps",
    ],

    LinkedinAdsResource.CampaignStats: [
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
        "follows"
    ],
    LinkedinAdsResource.CampaignGroupStats: [
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
        "follows"
    ],
}
