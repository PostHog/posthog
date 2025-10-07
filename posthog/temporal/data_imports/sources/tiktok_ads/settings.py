from dataclasses import dataclass
from typing import Optional

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.warehouse.types import IncrementalField, IncrementalFieldType

MAX_TIKTOK_DAYS_TO_QUERY = 30
BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"
TIKTOK_SLEEP_SECONDS = (
    1  # sleep between date intervals chunks requests to avoid rate limiting, tiktok has a 20 QPS limit
)
MAX_TIKTOK_DAYS_FOR_REPORT_ENDPOINTS = 365

TIKTOK_REPORT_METRICS = '["cpm", "ctr", "spend", "clicks", "conversion", "impressions", "conversion_rate", "cost_per_conversion", "real_time_conversion", "real_time_conversion_rate", "real_time_cost_per_conversion", "currency"]'


@dataclass
class EndpointConfig:
    partition_keys: list[str]
    partition_mode: PartitionMode
    resource: EndpointResource
    incremental_fields: Optional[list[IncrementalField]] = None
    partition_format: Optional[PartitionFormat] = None
    partition_size: int = 1


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
    ),
}
