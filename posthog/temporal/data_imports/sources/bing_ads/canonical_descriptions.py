"""Canonical, documentation-sourced descriptions for Bing Ads (Microsoft Advertising) endpoints and columns.

Sourced from the official Microsoft Advertising API reference
(https://learn.microsoft.com/en-us/advertising/guides/). Keyed by the resource names in `schemas.py`
`RESOURCE_SCHEMAS`, which match the `ExternalDataSchema.name` of a synced Bing Ads table. Columns
absent here fall back to LLM enrichment.
"""

from posthog.temporal.data_imports.sources.common.canonical_descriptions import CanonicalDescriptions

# Performance-report metrics shared by the campaign/ad-group/ad reports.
_REPORT_METRICS = {
    "AccountName": "Name of the Microsoft Advertising account.",
    "CampaignId": "Identifier of the campaign the row belongs to.",
    "CampaignName": "Name of the campaign the row belongs to.",
    "TimePeriod": "Date the aggregated metrics apply to.",
    "CurrencyCode": "Three-letter ISO currency code for the monetary metrics.",
    "Impressions": "Number of times the ad was shown.",
    "Clicks": "Number of clicks the ad received.",
    "Ctr": "Click-through rate — clicks divided by impressions.",
    "Spend": "Total amount spent over the period.",
    "AverageCpc": "Average cost per click.",
    "AverageCpm": "Average cost per thousand impressions.",
    "Conversions": "Number of conversions attributed over the period.",
    "ConversionRate": "Conversions divided by clicks.",
    "CostPerConversion": "Average cost per conversion.",
    "Revenue": "Revenue attributed to the ads over the period.",
    "ReturnOnAdSpend": "Return on ad spend — revenue divided by spend.",
    "Assists": "Number of conversions the ad assisted but did not directly drive.",
}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "A Microsoft Advertising campaign — a container for ad groups, budget, and targeting settings.",
        "docs_url": "https://learn.microsoft.com/en-us/advertising/campaign-management-service/campaign",
        "columns": {
            "Id": "Unique identifier of the campaign.",
            "Name": "Name of the campaign.",
            "Status": "Campaign status (e.g. Active, Paused, BudgetPaused).",
            "CampaignType": "Type of campaign (e.g. Search, Shopping, DynamicSearchAds, Audience).",
            "BudgetType": "How the budget is applied (e.g. DailyBudgetStandard, DailyBudgetAccelerated).",
            "DailyBudget": "Daily spending limit for the campaign.",
            "TimeZone": "Time zone the campaign's schedule and reporting use.",
            "Languages": "Languages the campaign targets.",
            "AudienceAdsBidAdjustment": "Percentage bid adjustment applied to audience ads.",
        },
    },
    "campaign_performance_report": {
        "description": "Daily performance metrics for campaigns — impressions, clicks, spend, and conversions.",
        "docs_url": "https://learn.microsoft.com/en-us/advertising/reporting-service/campaignperformancereportrequest",
        "columns": {
            **_REPORT_METRICS,
            "AbsoluteTopImpressionSharePercent": "Percentage of impressions shown in the very top position.",
            "TopImpressionSharePercent": "Percentage of impressions shown in a top position above search results.",
            "ImpressionSharePercent": "Share of impressions received out of those the ad was eligible for.",
            "ImpressionLostToBudgetPercent": "Share of impressions lost because of insufficient budget.",
            "ImpressionLostToRankAggPercent": "Share of impressions lost because of ad rank.",
            "QualityScore": "Microsoft's measure of how competitive the campaign's ads are.",
            "ExpectedCtr": "Expected click-through rate component of quality score.",
            "AdRelevance": "Ad relevance component of quality score.",
            "LandingPageExperience": "Landing page experience component of quality score.",
        },
    },
    "ad_group_performance_report": {
        "description": "Daily performance metrics broken down by ad group.",
        "docs_url": "https://learn.microsoft.com/en-us/advertising/reporting-service/adgroupperformancereportrequest",
        "columns": {
            **_REPORT_METRICS,
            "AdGroupId": "Identifier of the ad group the row belongs to.",
            "AdGroupName": "Name of the ad group the row belongs to.",
            "AbsoluteTopImpressionSharePercent": "Percentage of impressions shown in the very top position.",
            "TopImpressionSharePercent": "Percentage of impressions shown in a top position above search results.",
            "ImpressionSharePercent": "Share of impressions received out of those the ad group was eligible for.",
            "ImpressionLostToBudgetPercent": "Share of impressions lost because of insufficient budget.",
            "ImpressionLostToRankAggPercent": "Share of impressions lost because of ad rank.",
            "QualityScore": "Microsoft's measure of how competitive the ad group's ads are.",
            "ExpectedCtr": "Expected click-through rate component of quality score.",
            "AdRelevance": "Ad relevance component of quality score.",
            "LandingPageExperience": "Landing page experience component of quality score.",
        },
    },
    "ad_performance_report": {
        "description": "Daily performance metrics broken down by individual ad.",
        "docs_url": "https://learn.microsoft.com/en-us/advertising/reporting-service/adperformancereportrequest",
        "columns": {
            **_REPORT_METRICS,
            "AdGroupId": "Identifier of the ad group the ad belongs to.",
            "AdGroupName": "Name of the ad group the ad belongs to.",
            "AdId": "Identifier of the ad the row belongs to.",
            "AdTitle": "Title text of the ad.",
            "AdType": "Type of the ad (e.g. TextAd, ResponsiveSearchAd, ProductAd).",
        },
    },
}
