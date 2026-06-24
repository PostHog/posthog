"""Canonical, documentation-sourced descriptions for LinkedIn Ads endpoints and columns.

Sourced from the official LinkedIn Marketing API reference
(https://learn.microsoft.com/en-us/linkedin/marketing). Keyed by the `resource_name` values in
`schemas.py` `RESOURCE_SCHEMAS`, which match the `ExternalDataSchema.name` of a synced table. URN
reference fields are flattened into `*_id` virtual columns (e.g. `campaign_id`, `account_id`) and
analytics date ranges into `date_start` / `date_end` during sync. Columns absent here fall back to
LLM enrichment.
"""

from posthog.temporal.data_imports.sources.common.canonical_descriptions import CanonicalDescriptions

# Metrics shared by every analytics (stats) resource; merged into each stats entry.
_STATS_COLUMNS = {
    "date_start": "Start date of the reporting period for this row.",
    "date_end": "End date of the reporting period for this row.",
    "impressions": "Number of times an ad was shown.",
    "clicks": "Number of clicks on the ad.",
    "costInUsd": "Amount spent in USD over the reporting period.",
    "costInLocalCurrency": "Amount spent in the account's local currency over the reporting period.",
    "externalWebsiteConversions": "Conversions tracked on an external website attributed to the ad.",
    "conversionValueInLocalCurrency": "Total value of conversions in the account's local currency.",
    "landingPageClicks": "Clicks that led to the ad's landing page.",
    "totalEngagements": "Total engagements (clicks, reactions, comments, shares, follows) on the ad.",
    "videoViews": "Number of video views.",
    "videoCompletions": "Number of times the video was watched to completion.",
    "oneClickLeads": "Leads collected via one-click LinkedIn Lead Gen forms.",
    "follows": "Number of new followers attributed to the ad.",
}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "A LinkedIn advertising account (ad account) used to run and bill campaigns.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-accounts",
        "columns": {
            "id": "Unique identifier for the ad account.",
            "name": "The ad account's name.",
            "status": "Status of the ad account (e.g. ACTIVE, CANCELED, DRAFT).",
            "type": "Type of the ad account (e.g. BUSINESS, ENTERPRISE).",
            "currency": "The account's billing currency.",
            "version": "Version metadata for optimistic concurrency.",
        },
    },
    "campaigns": {
        "description": "A LinkedIn ad campaign — a budget, schedule, and targeting wrapper around creatives.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-campaigns",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "name": "The campaign's name.",
            "account_id": "ID of the ad account the campaign belongs to.",
            "campaign_group_id": "ID of the campaign group the campaign belongs to.",
            "status": "Status of the campaign (e.g. ACTIVE, PAUSED, DRAFT, COMPLETED, ARCHIVED).",
            "type": "The campaign's type (e.g. SPONSORED_UPDATES, TEXT_AD).",
            "costType": "How the campaign is charged (e.g. CPC, CPM, CPV).",
            "dailyBudget": "The campaign's daily budget.",
            "unitCost": "Bid amount per unit (click, impression, etc.).",
            "runSchedule": "Start and end schedule for the campaign.",
            "targetingCriteria": "The audience targeting criteria applied to the campaign.",
            "locale": "The campaign's locale.",
            "changeAuditStamps": "Created and last-modified audit timestamps.",
            "created_time": "Time the campaign was created.",
            "version": "Version metadata for optimistic concurrency.",
        },
    },
    "campaign_groups": {
        "description": "A group of LinkedIn ad campaigns sharing a budget and schedule.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-campaign-groups",
        "columns": {
            "id": "Unique identifier for the campaign group.",
            "name": "The campaign group's name.",
            "account_id": "ID of the ad account the campaign group belongs to.",
            "status": "Status of the campaign group (e.g. ACTIVE, PAUSED, DRAFT, ARCHIVED).",
            "totalBudget": "The campaign group's total budget.",
            "runSchedule": "Start and end schedule for the campaign group.",
            "changeAuditStamps": "Created and last-modified audit timestamps.",
            "created_time": "Time the campaign group was created.",
        },
    },
    "creatives": {
        "description": "A LinkedIn ad creative — the content shown to members within a campaign.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-creatives",
        "columns": {
            "id": "Unique identifier for the creative.",
            "name": "The creative's name.",
            "account_id": "ID of the ad account the creative belongs to.",
            "campaign_id": "ID of the campaign the creative belongs to.",
            "intendedStatus": "The creative's intended status (e.g. ACTIVE, PAUSED, DRAFT).",
            "isServing": "Whether the creative is currently being served.",
            "review": "The creative's ad review status.",
            "createdAt": "Time the creative was created.",
            "lastModifiedAt": "Time the creative was last modified.",
            "created_time": "Time the creative was created.",
        },
    },
    "campaign_stats": {
        "description": "Daily performance analytics for LinkedIn ad campaigns, pivoted by campaign.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting",
        "columns": {
            **_STATS_COLUMNS,
            "campaign_id": "ID of the campaign these metrics are for.",
        },
    },
    "campaign_group_stats": {
        "description": "Daily performance analytics for LinkedIn ad campaign groups, pivoted by campaign group.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting",
        "columns": {
            **_STATS_COLUMNS,
            "campaign_group_id": "ID of the campaign group these metrics are for.",
        },
    },
    "creative_stats": {
        "description": "Daily performance analytics for LinkedIn ad creatives, pivoted by creative.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting",
        "columns": {
            **_STATS_COLUMNS,
            "creative_id": "ID of the creative these metrics are for.",
        },
    },
}
