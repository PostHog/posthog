import json
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.warehouse.types import IncrementalField, IncrementalFieldType

MAX_TIKTOK_DAYS_TO_QUERY = 29
BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"
MAX_TIKTOK_DAYS_FOR_REPORT_ENDPOINTS = 365

METRICS_FIELDS = [
    "app_promotion_type",
    "average_video_play_per_user",
    "average_video_play",
    "billing_event",
    "campaign_budget",
    "campaign_dedicate_type",
    "campaign_name",
    "clicks_on_music_disc",
    "clicks",
    "comments",
    "conversion_rate_v2",
    "conversion_rate",
    "conversion",
    "cost_per_1000_reached",
    "cost_per_conversion",
    "cost_per_result",
    "cost_per_secondary_goal_result",
    "cpc",
    "cpm",
    "ctr",
    "currency",
    "follows",
    "frequency",
    "gross_impressions",
    "impressions",
    "likes",
    "profile_visits_rate",
    "profile_visits",
    "reach",
    "real_time_conversion_rate_v2",
    "real_time_conversion_rate",
    "real_time_conversion",
    "real_time_cost_per_conversion",
    "real_time_cost_per_result",
    "real_time_result_rate",
    "real_time_result",
    "result_rate",
    "result",
    "secondary_goal_result_rate",
    "secondary_goal_result",
    "shares",
    "spend",
    "split_test",
    "video_play_actions",
    "video_views_p100",
    "video_views_p25",
    "video_views_p50",
    "video_views_p75",
    "video_watched_2s",
    "video_watched_6s",
]

TIKTOK_REPORT_METRICS = json.dumps(METRICS_FIELDS)

ENDPOINT_ADVERTISERS = ["advertisers"]
ENDPOINT_AD_MANAGEMENT = ["campaigns", "adgroups", "ads"]
ENDPOINT_INSIGHTS = ["campaign_report", "ad_group_report", "ad_report"]


class EndpointType(str, Enum):
    ACCOUNT = "account"
    ENTITY = "entity"
    REPORT = "report"


@dataclass
class EndpointConfig:
    partition_keys: list[str]
    partition_mode: PartitionMode
    resource: EndpointResource
    incremental_fields: Optional[list[IncrementalField]] = None
    partition_format: Optional[PartitionFormat] = None
    partition_size: int = 1
    endpoint_type: Optional[EndpointType] = None


TIKTOK_ADS_CONFIG: dict[str, EndpointConfig] = {
    "campaigns": EndpointConfig(
        resource={
            # Docs: https://business-api.tiktok.com/portal/docs?id=1739315828649986
            "name": "campaigns",
            "table_name": "campaigns",
            "primary_key": ["campaign_id"],
            "endpoint": {
                "path": "/campaign/get/",
                "method": "GET",
                "params": {
                    "advertiser_id": "{advertiser_id}",
                    "page_size": 1000,
                    "page": 1,
                },
                "data_selector": "data.list",
            },
            "table_format": "delta",
        },
        incremental_fields=None,
        partition_keys=["create_time"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
        endpoint_type=EndpointType.ENTITY,
    ),
    "ad_groups": EndpointConfig(
        # Docs: https://business-api.tiktok.com/portal/docs?id=1739314558673922
        resource={
            "name": "ad_groups",
            "table_name": "ad_groups",
            "primary_key": ["adgroup_id"],
            "endpoint": {
                "path": "/adgroup/get/",
                "method": "GET",
                "params": {
                    "advertiser_id": "{advertiser_id}",
                    "page_size": 1000,
                    "page": 1,
                },
                "data_selector": "data.list",
            },
            "table_format": "delta",
        },
        incremental_fields=None,
        partition_keys=["create_time"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
        endpoint_type=EndpointType.ENTITY,
    ),
    "ads": EndpointConfig(
        # Docs: https://business-api.tiktok.com/portal/docs?id=1735735588640770
        resource={
            "name": "ads",
            "table_name": "ads",
            "primary_key": ["ad_id"],
            "endpoint": {
                "path": "/ad/get/",
                "method": "GET",
                "params": {
                    "advertiser_id": "{advertiser_id}",
                    "page_size": 1000,
                    "page": 1,
                },
                "data_selector": "data.list",
            },
            "table_format": "delta",
        },
        incremental_fields=None,
        partition_keys=["create_time"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
        endpoint_type=EndpointType.ENTITY,
    ),
    "campaign_report": EndpointConfig(
        resource={
            # Docs: https://business-api.tiktok.com/portal/docs?id=1740302848100353
            "name": "campaign_report",
            "table_name": "campaign_report",
            "primary_key": ["campaign_id", "stat_time_day"],
            "endpoint": {
                "path": "/report/integrated/get/",
                "method": "GET",
                "params": {
                    "advertiser_id": "{advertiser_id}",
                    "service_type": "AUCTION",
                    "report_type": "BASIC",
                    "data_level": "AUCTION_CAMPAIGN",
                    "dimensions": '["campaign_id", "stat_time_day"]',
                    "metrics": TIKTOK_REPORT_METRICS,
                    "page_size": 1000,
                    "start_date": "{start_date}",
                    "end_date": "{end_date}",
                },
                "data_selector": "data.list",
                "incremental": {
                    "cursor_path": "stat_time_day",
                    "start_param": "start_date",
                    "end_param": "end_date",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "stat_time_day",
                "type": IncrementalFieldType.Date,
                "field": "stat_time_day",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_keys=["stat_time_day"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
        endpoint_type=EndpointType.REPORT,
    ),
    "ad_group_report": EndpointConfig(
        # Docs: https://business-api.tiktok.com/portal/docs?id=1740302848100353
        resource={
            "name": "ad_group_report",
            "table_name": "ad_group_report",
            "primary_key": ["adgroup_id", "stat_time_day"],
            "endpoint": {
                "path": "/report/integrated/get/",
                "method": "GET",
                "params": {
                    "advertiser_id": "{advertiser_id}",
                    "service_type": "AUCTION",
                    "report_type": "BASIC",
                    "data_level": "AUCTION_ADGROUP",
                    "dimensions": '["adgroup_id", "stat_time_day"]',
                    "metrics": TIKTOK_REPORT_METRICS,
                    "page_size": 1000,
                    "start_date": "{start_date}",
                    "end_date": "{end_date}",
                },
                "data_selector": "data.list",
                "incremental": {
                    "cursor_path": "stat_time_day",
                    "start_param": "start_date",
                    "end_param": "end_date",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "stat_time_day",
                "type": IncrementalFieldType.Date,
                "field": "stat_time_day",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_keys=["stat_time_day"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
        endpoint_type=EndpointType.REPORT,
    ),
    "ad_report": EndpointConfig(
        # Docs: https://business-api.tiktok.com/portal/docs?id=1740302848100353
        resource={
            "name": "ad_report",
            "table_name": "ad_report",
            "primary_key": ["ad_id", "stat_time_day"],
            "endpoint": {
                "path": "/report/integrated/get/",
                "method": "GET",
                "params": {
                    "advertiser_id": "{advertiser_id}",
                    "service_type": "AUCTION",
                    "report_type": "BASIC",
                    "data_level": "AUCTION_AD",
                    "dimensions": '["ad_id", "stat_time_day"]',
                    "metrics": TIKTOK_REPORT_METRICS,
                    "page_size": 1000,
                    "start_date": "{start_date}",
                    "end_date": "{end_date}",
                },
                "data_selector": "data.list",
                "incremental": {
                    "cursor_path": "stat_time_day",
                    "start_param": "start_date",
                    "end_param": "end_date",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "stat_time_day",
                "type": IncrementalFieldType.Date,
                "field": "stat_time_day",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_keys=["stat_time_day"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
        endpoint_type=EndpointType.REPORT,
    ),
}
