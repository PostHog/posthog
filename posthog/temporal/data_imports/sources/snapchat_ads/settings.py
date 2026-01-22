from dataclasses import dataclass
from enum import Enum
from typing import Optional

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

# With granularity DAY there is a max of 31 days https://developers.snap.com/api/marketing-api/Ads-API/measurement
MAX_SNAPCHAT_DAYS_TO_QUERY = 31
BASE_URL = "https://adsapi.snapchat.com/v1"

# Stats metrics to request from Snapchat API
# Docs: https://developers.snap.com/api/marketing-api/Ads-API/measurement
METRICS_FIELDS = [
    # Core delivery metrics
    "impressions",
    "swipes",  # AKA clicks
    "spend",
    "swipe_up_percent",
    # Video metrics
    "video_views",
    "video_views_time_based",
    "video_views_5s",
    "video_views_15s",
    "screen_time_millis",
    "avg_screen_time_millis",
    "quartile_1",
    "quartile_2",
    "quartile_3",
    "view_completion",
    # Audience metrics
    "frequency",
    "uniques",
    # Attachment metrics
    "attachment_avg_view_time_millis",
    "attachment_total_view_time_millis",
    "attachment_video_views",
    "attachment_quartile_1",
    "attachment_quartile_2",
    "attachment_quartile_3",
    "attachment_view_completion",
    # Engagement metrics
    "saves",
    "shares",
    "story_opens",
    "story_completes",
    # Install metrics
    "total_installs",
    "android_installs",
    "ios_installs",
    # Conversion metrics
    "conversion_purchases",
    "conversion_purchases_value",
    "conversion_sign_ups",
    "conversion_sign_ups_value",
    "conversion_add_cart",
    "conversion_add_cart_value",
    "conversion_view_content",
    "conversion_view_content_value",
    "conversion_page_views",
    "conversion_page_views_value",
    "conversion_app_opens",
    "conversion_app_opens_value",
    "conversion_start_checkout",
    "conversion_start_checkout_value",
    "conversion_add_billing",
    "conversion_add_billing_value",
    "conversion_searches",
    "conversion_searches_value",
    "conversion_level_completes",
    "conversion_level_completes_value",
    "conversion_subscribe",
    "conversion_subscribe_value",
    "conversion_ad_click",
    "conversion_ad_click_value",
    "conversion_ad_view",
    "conversion_ad_view_value",
    "conversion_complete_tutorial",
    "conversion_complete_tutorial_value",
    "conversion_invite",
    "conversion_invite_value",
    "conversion_login",
    "conversion_login_value",
    "conversion_share",
    "conversion_share_value",
    "conversion_reserve",
    "conversion_reserve_value",
    "conversion_achievement_unlocked",
    "conversion_achievement_unlocked_value",
    "conversion_add_to_wishlist",
    "conversion_add_to_wishlist_value",
    "conversion_spend_credits",
    "conversion_spend_credits_value",
    "conversion_rate",
    "conversion_rate_value",
    "conversion_start_trial",
    "conversion_start_trial_value",
    "conversion_list_view",
    "conversion_list_view_value",
    # Custom events
    "custom_event_1",
    "custom_event_1_value",
    "custom_event_2",
    "custom_event_2_value",
    "custom_event_3",
    "custom_event_3_value",
    "custom_event_4",
    "custom_event_4_value",
    "custom_event_5",
    "custom_event_5_value",
]

SNAPCHAT_STATS_METRICS = ",".join(METRICS_FIELDS)


class EndpointType(str, Enum):
    ACCOUNT = "account"
    ENTITY = "entity"
    STATS = "stats"


@dataclass
class EndpointConfig:
    partition_keys: list[str]
    partition_mode: PartitionMode
    resource: EndpointResource
    incremental_fields: Optional[list[IncrementalField]] = None
    partition_format: Optional[PartitionFormat] = None
    partition_size: int = 1
    endpoint_type: Optional[EndpointType] = None


SNAPCHAT_ADS_CONFIG: dict[str, EndpointConfig] = {
    "campaigns": EndpointConfig(
        resource={
            # Docs: https://developers.snap.com/api/marketing-api/Ads-API/campaigns
            "name": "campaigns",
            "table_name": "campaigns",
            "primary_key": ["id"],
            "endpoint": {
                "path": "/adaccounts/{ad_account_id}/campaigns",
                "method": "GET",
                "params": {
                    "limit": 1000,
                },
                "data_selector": "campaigns",
            },
            "table_format": "delta",
        },
        incremental_fields=None,
        partition_keys=["created_at"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
        endpoint_type=EndpointType.ENTITY,
    ),
    "ad_squads": EndpointConfig(
        resource={
            # Docs: https://developers.snap.com/api/marketing-api/Ads-API/ad-squads
            "name": "ad_squads",
            "table_name": "ad_squads",
            "primary_key": ["id"],
            "endpoint": {
                "path": "/adaccounts/{ad_account_id}/adsquads",
                "method": "GET",
                "params": {
                    "limit": 1000,
                },
                "data_selector": "adsquads",
            },
            "table_format": "delta",
        },
        incremental_fields=None,
        partition_keys=["created_at"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
        endpoint_type=EndpointType.ENTITY,
    ),
    "ads": EndpointConfig(
        resource={
            # Docs: https://developers.snap.com/api/marketing-api/Ads-API/ads
            "name": "ads",
            "table_name": "ads",
            "primary_key": ["id"],
            "endpoint": {
                "path": "/adaccounts/{ad_account_id}/ads",
                "method": "GET",
                "params": {
                    "limit": 1000,
                },
                "data_selector": "ads",
            },
            "table_format": "delta",
        },
        incremental_fields=None,
        partition_keys=["created_at"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
        endpoint_type=EndpointType.ENTITY,
    ),
    "campaign_stats_daily": EndpointConfig(
        resource={
            # Docs: https://developers.snap.com/api/marketing-api/Ads-API/measurement
            "name": "campaign_stats_daily",
            "table_name": "campaign_stats_daily",
            "primary_key": ["id", "start_time"],
            "endpoint": {
                "path": "/adaccounts/{ad_account_id}/stats",
                "method": "GET",
                "params": {
                    "granularity": "DAY",
                    "fields": SNAPCHAT_STATS_METRICS,
                    "breakdown": "campaign",
                    "start_time": "{start_time}",
                    "end_time": "{end_time}",
                    "omit_empty": "false",
                    "limit": 1000,
                },
                "data_selector": "timeseries_stats",
                "incremental": {
                    "cursor_path": "start_time",
                    "start_param": "start_time",
                    "end_param": "end_time",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "start_time",
                "type": IncrementalFieldType.DateTime,
                "field": "start_time",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_keys=["start_time"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
        endpoint_type=EndpointType.STATS,
    ),
    "ad_squad_stats_daily": EndpointConfig(
        resource={
            # Docs: https://developers.snap.com/api/marketing-api/Ads-API/measurement
            "name": "ad_squad_stats_daily",
            "table_name": "ad_squad_stats_daily",
            "primary_key": ["id", "start_time"],
            "endpoint": {
                "path": "/adaccounts/{ad_account_id}/stats",
                "method": "GET",
                "params": {
                    "granularity": "DAY",
                    "fields": SNAPCHAT_STATS_METRICS,
                    "breakdown": "adsquad",
                    "start_time": "{start_time}",
                    "end_time": "{end_time}",
                    "omit_empty": "false",
                    "limit": 1000,
                },
                "data_selector": "timeseries_stats",
                "incremental": {
                    "cursor_path": "start_time",
                    "start_param": "start_time",
                    "end_param": "end_time",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "start_time",
                "type": IncrementalFieldType.DateTime,
                "field": "start_time",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_keys=["start_time"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
        endpoint_type=EndpointType.STATS,
    ),
    "ad_stats_daily": EndpointConfig(
        resource={
            # Docs: https://developers.snap.com/api/marketing-api/Ads-API/measurement
            "name": "ad_stats_daily",
            "table_name": "ad_stats_daily",
            "primary_key": ["id", "start_time"],
            "endpoint": {
                "path": "/adaccounts/{ad_account_id}/stats",
                "method": "GET",
                "params": {
                    "granularity": "DAY",
                    "fields": SNAPCHAT_STATS_METRICS,
                    "breakdown": "ad",
                    "start_time": "{start_time}",
                    "end_time": "{end_time}",
                    "omit_empty": "false",
                    "limit": 1000,
                },
                "data_selector": "timeseries_stats",
                "incremental": {
                    "cursor_path": "start_time",
                    "start_param": "start_time",
                    "end_param": "end_time",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "start_time",
                "type": IncrementalFieldType.DateTime,
                "field": "start_time",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_keys=["start_time"],
        partition_mode="datetime",
        partition_format="week",
        partition_size=1,
        endpoint_type=EndpointType.STATS,
    ),
}
