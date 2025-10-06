from dataclasses import dataclass
from typing import Optional

from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.warehouse.types import IncrementalField, IncrementalFieldType


@dataclass
class EndpointConfig:
    partition_keys: list[str]
    partition_mode: PartitionMode
    resource: EndpointResource
    incremental_fields: Optional[list[IncrementalField]] = None
    partition_format: Optional[PartitionFormat] = None
    partition_size: int = 1


REDDIT_ADS_CONFIG: dict[str, EndpointConfig] = {
    "campaigns": EndpointConfig(
        resource={
            "name": "campaigns",
            "table_name": "campaigns",
            "primary_key": ["id"],
            "endpoint": {
                "path": "/ad_accounts/{account_id}/campaigns",
                "method": "GET",
                "params": {"page.size": 100},
                "data_selector": "data",
                "incremental": {
                    "cursor_path": "modified_at",
                    "start_param": "modified_at",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "modified_at",
                "type": IncrementalFieldType.DateTime,
                "field": "modified_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_keys=["created_at"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
    ),
    "ad_groups": EndpointConfig(
        resource={
            "name": "ad_groups",
            "table_name": "ad_groups",
            "primary_key": ["id"],
            "endpoint": {
                "path": "/ad_accounts/{account_id}/ad_groups",
                "method": "GET",
                "params": {"page.size": 100},
                "data_selector": "data",
                "incremental": {
                    "cursor_path": "modified_at",
                    "start_param": "modified_at",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "modified_at",
                "type": IncrementalFieldType.DateTime,
                "field": "modified_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_keys=["created_at"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
    ),
    "ads": EndpointConfig(
        resource={
            "name": "ads",
            "table_name": "ads",
            "primary_key": ["id"],
            "endpoint": {
                "path": "/ad_accounts/{account_id}/ads",
                "method": "GET",
                "params": {"page.size": 100},
                "data_selector": "data",
                "incremental": {
                    "cursor_path": "modified_at",
                    "start_param": "modified_at",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "modified_at",
                "type": IncrementalFieldType.DateTime,
                "field": "modified_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_keys=["created_at"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
    ),
    "campaign_report": EndpointConfig(
        resource={
            "name": "campaign_report",
            "table_name": "campaign_report",
            "primary_key": ["campaign_id", "date"],
            "endpoint": {
                "path": "/ad_accounts/{account_id}/reports",
                "method": "POST",
                "params": {"page.size": 100},
                "json": {
                    "data": {
                        "breakdowns": ["CAMPAIGN_ID", "DATE"],
                        "fields": [
                            "APP_INSTALL_INSTALL_COUNT",
                            "APP_INSTALL_PURCHASE_COUNT",
                            "APP_INSTALL_REVENUE",
                            "APP_INSTALL_ROAS_DOUBLE",
                            "CAMPAIGN_ID",
                            "CLICKS",
                            "CONVERSION_PURCHASE_TOTAL_ITEMS",
                            "CONVERSION_PURCHASE_TOTAL_VALUE",
                            "CONVERSION_ROAS",
                            "CONVERSION_SIGN_UP_VIEWS",
                            "CONVERSION_SIGNUP_TOTAL_VALUE",
                            "CPC",
                            "CTR",
                            "CURRENCY",
                            "DATE",
                            "ECPM",
                            "FREQUENCY",
                            "IMPRESSIONS",
                            "KEY_CONVERSION_RATE",
                            "KEY_CONVERSION_TOTAL_COUNT",
                            "REACH",
                            "SPEND",
                            "VIDEO_COMPLETION_RATE",
                            "VIDEO_STARTED",
                            "VIDEO_VIEW_RATE",
                            "VIDEO_WATCHED_100_PERCENT",
                            "VIDEO_WATCHED_25_PERCENT",
                            "VIDEO_WATCHED_50_PERCENT",
                            "VIDEO_WATCHED_75_PERCENT",
                        ],
                        "starts_at": None,  # Will be set dynamically
                        "ends_at": None,  # Will be set dynamically
                        "time_zone_id": "UTC",
                    }
                },
                "data_selector": "data.metrics",
                "incremental": {
                    "cursor_path": "date",
                    "start_param": "starts_at",
                    "end_param": "ends_at",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
    ),
    "ad_group_report": EndpointConfig(
        resource={
            "name": "ad_group_report",
            "table_name": "ad_group_report",
            "primary_key": ["ad_group_id", "date"],
            "endpoint": {
                "path": "/ad_accounts/{account_id}/reports",
                "method": "POST",
                "params": {"page.size": 100},
                "json": {
                    "data": {
                        "breakdowns": ["AD_GROUP_ID", "DATE"],
                        "fields": [
                            "AD_GROUP_ID",
                            "APP_INSTALL_INSTALL_COUNT",
                            "APP_INSTALL_PURCHASE_COUNT",
                            "APP_INSTALL_REVENUE",
                            "APP_INSTALL_ROAS_DOUBLE",
                            "CLICKS",
                            "CONVERSION_PURCHASE_TOTAL_ITEMS",
                            "CONVERSION_PURCHASE_TOTAL_VALUE",
                            "CONVERSION_ROAS",
                            "CONVERSION_SIGN_UP_VIEWS",
                            "CONVERSION_SIGNUP_TOTAL_VALUE",
                            "CPC",
                            "CTR",
                            "CURRENCY",
                            "ECPM",
                            "FREQUENCY",
                            "IMPRESSIONS",
                            "KEY_CONVERSION_RATE",
                            "KEY_CONVERSION_TOTAL_COUNT",
                            "REACH",
                            "SPEND",
                            "VIDEO_COMPLETION_RATE",
                            "VIDEO_STARTED",
                            "VIDEO_VIEW_RATE",
                            "VIDEO_WATCHED_100_PERCENT",
                            "VIDEO_WATCHED_25_PERCENT",
                            "VIDEO_WATCHED_50_PERCENT",
                            "VIDEO_WATCHED_75_PERCENT",
                        ],
                        "starts_at": None,  # Will be set dynamically
                        "ends_at": None,  # Will be set dynamically
                        "time_zone_id": "UTC",
                    }
                },
                "data_selector": "data.metrics",
                "incremental": {
                    "cursor_path": "date",
                    "start_param": "starts_at",
                    "end_param": "ends_at",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
    ),
    "ad_report": EndpointConfig(
        resource={
            "name": "ad_report",
            "table_name": "ad_report",
            "primary_key": ["ad_id", "date"],
            "endpoint": {
                "path": "/ad_accounts/{account_id}/reports",
                "method": "POST",
                "params": {"page.size": 100},
                "json": {
                    "data": {
                        "breakdowns": ["AD_ID", "DATE"],
                        "fields": [
                            "AD_ID",
                            "APP_INSTALL_INSTALL_COUNT",
                            "APP_INSTALL_PURCHASE_COUNT",
                            "APP_INSTALL_REVENUE",
                            "APP_INSTALL_ROAS_DOUBLE",
                            "CLICKS",
                            "CONVERSION_PURCHASE_TOTAL_ITEMS",
                            "CONVERSION_PURCHASE_TOTAL_VALUE",
                            "CONVERSION_ROAS",
                            "CONVERSION_SIGN_UP_VIEWS",
                            "CONVERSION_SIGNUP_TOTAL_VALUE",
                            "CPC",
                            "CTR",
                            "CURRENCY",
                            "DATE",
                            "ECPM",
                            "FREQUENCY",
                            "IMPRESSIONS",
                            "KEY_CONVERSION_RATE",
                            "KEY_CONVERSION_TOTAL_COUNT",
                            "REACH",
                            "SPEND",
                            "VIDEO_COMPLETION_RATE",
                            "VIDEO_STARTED",
                            "VIDEO_VIEW_RATE",
                            "VIDEO_WATCHED_100_PERCENT",
                            "VIDEO_WATCHED_25_PERCENT",
                            "VIDEO_WATCHED_50_PERCENT",
                            "VIDEO_WATCHED_75_PERCENT",
                        ],
                        "starts_at": None,  # Will be set dynamically
                        "ends_at": None,  # Will be set dynamically
                        "time_zone_id": "UTC",
                    }
                },
                "data_selector": "data.metrics",
                "incremental": {
                    "cursor_path": "date",
                    "start_param": "starts_at",
                    "end_param": "ends_at",
                },
            },
            "table_format": "delta",
        },
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
    ),
}
