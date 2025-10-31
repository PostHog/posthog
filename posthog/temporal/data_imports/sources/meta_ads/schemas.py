from enum import StrEnum
from typing import Any

from posthog.warehouse.types import IncrementalField, IncrementalFieldType


class MetaAdsResource(StrEnum):
    Campaigns = "campaigns"
    CampaignStats = "campaign_stats"
    Adsets = "adsets"
    AdStats = "ad_stats"
    Ads = "ads"
    AdsetStats = "adset_stats"  # TODO: remove this


ENDPOINTS = (
    MetaAdsResource.Campaigns,
    MetaAdsResource.CampaignStats,
    MetaAdsResource.Adsets,
    MetaAdsResource.AdsetStats,
    MetaAdsResource.Ads,
    MetaAdsResource.AdStats,
)

INCREMENTAL_ENDPOINTS = (
    MetaAdsResource.AdStats,
    MetaAdsResource.AdsetStats,
    MetaAdsResource.CampaignStats,
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    MetaAdsResource.AdStats: [
        {
            "label": "date_start",
            "type": IncrementalFieldType.Date,
            "field": "date_start",
            "field_type": IncrementalFieldType.Date,
        }
    ],
    MetaAdsResource.AdsetStats: [
        {
            "label": "date_start",
            "type": IncrementalFieldType.Date,
            "field": "date_start",
            "field_type": IncrementalFieldType.Date,
        }
    ],
    MetaAdsResource.CampaignStats: [
        {
            "label": "date_start",
            "type": IncrementalFieldType.Date,
            "field": "date_start",
            "field_type": IncrementalFieldType.Date,
        }
    ],
}

RESOURCE_SCHEMAS: dict[MetaAdsResource, dict[str, Any]] = {
    MetaAdsResource.Ads: {
        "primary_keys": ["id", "account_id"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/ads",
        "extra_params": {},
        "field_names": [
            "id",
            "account_id",
            "adset_id",
            "campaign_id",
            "name",
            "status",
            "configured_status",
            "effective_status",
            "creative",
            "bid_amount",
            "created_time",
            "updated_time",
            "tracking_specs",
            "conversion_specs",
        ],
        "partition_mode": "datetime",
        "partition_format": "month",
        "partition_keys": ["created_time"],
    },
    MetaAdsResource.AdStats: {
        "primary_keys": ["ad_id", "account_id", "date_start"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/insights",
        "extra_params": {
            "level": "ad",
            "time_increment": 1,  # daily
        },
        "field_names": [
            "ad_id",
            "account_id",
            "account_currency",
            "adset_id",
            "campaign_id",
            "date_start",
            "date_stop",
            "impressions",
            "clicks",
            "spend",
            "reach",
            "frequency",
            "cpm",
            "cpc",
            "ctr",
            "cpp",
            "cost_per_unique_click",
            "unique_clicks",
            "unique_ctr",
            "actions",
            "conversions",
            "conversion_values",
            "cost_per_action_type",
            "action_values",
            "video_30_sec_watched_actions",
            "video_p25_watched_actions",
            "video_p50_watched_actions",
            "video_p75_watched_actions",
            "video_p95_watched_actions",
            "video_p100_watched_actions",
        ],
        "partition_mode": "datetime",
        "partition_format": "month",
        "partition_keys": ["date_start"],
        "is_stats": True,
    },
    MetaAdsResource.Adsets: {
        "primary_keys": ["id", "account_id"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/adsets",
        "extra_params": {},
        "field_names": [
            "id",
            "account_id",
            "campaign_id",
            "name",
            "status",
            "configured_status",
            "effective_status",
            "optimization_goal",
            "billing_event",
            "bid_amount",
            "budget_remaining",
            "daily_budget",
            "lifetime_budget",
            "created_time",
            "updated_time",
            "start_time",
            "end_time",
            "targeting",
            "promoted_object",
        ],
        "partition_mode": "datetime",
        "partition_format": "month",
        "partition_keys": ["created_time"],
    },
    MetaAdsResource.AdsetStats: {
        "primary_keys": ["adset_id", "account_id", "date_start"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/insights",
        "extra_params": {
            "level": "adset",
            "time_increment": 1,  # daily
        },
        "field_names": [
            "adset_id",
            "account_id",
            "account_currency",
            "campaign_id",
            "date_start",
            "date_stop",
            "impressions",
            "clicks",
            "spend",
            "reach",
            "frequency",
            "cpm",
            "cpc",
            "ctr",
            "cpp",
            "cost_per_unique_click",
            "unique_clicks",
            "unique_ctr",
            "actions",
            "conversions",
            "conversion_values",
            "cost_per_action_type",
            "action_values",
        ],
        "partition_mode": "datetime",
        "partition_format": "month",
        "partition_keys": ["date_start"],
        "is_stats": True,
    },
    MetaAdsResource.Campaigns: {
        "primary_keys": ["id", "account_id"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/campaigns",
        "extra_params": {},
        "field_names": [
            "id",
            "account_id",
            "name",
            "status",
            "configured_status",
            "effective_status",
            "objective",
            "buying_type",
            "daily_budget",
            "lifetime_budget",
            "budget_remaining",
            "created_time",
            "updated_time",
            "start_time",
            "stop_time",
            "special_ad_categories",
        ],
        "partition_mode": "datetime",
        "partition_format": "month",
        "partition_keys": ["created_time"],
    },
    MetaAdsResource.CampaignStats: {
        "primary_keys": ["campaign_id", "account_id", "date_start"],
        "url": "https://graph.facebook.com/{API_VERSION}/{account_id}/insights",
        "extra_params": {
            "level": "campaign",
            "time_increment": 1,  # daily
        },
        "field_names": [
            "campaign_id",
            "account_id",
            "account_currency",
            "date_start",
            "date_stop",
            "impressions",
            "clicks",
            "spend",
            "reach",
            "frequency",
            "cpm",
            "cpc",
            "ctr",
            "cpp",
            "cost_per_unique_click",
            "unique_clicks",
            "unique_ctr",
            "actions",
            "conversions",
            "conversion_values",
            "cost_per_action_type",
            "action_values",
        ],
        "partition_mode": "datetime",
        "partition_format": "month",
        "partition_keys": ["date_start"],
        "is_stats": True,
    },
}
