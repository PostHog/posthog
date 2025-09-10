from dataclasses import dataclass
from typing import Any, Literal, Optional, Union

from posthog.warehouse.types import IncrementalFieldType


@dataclass
class EndpointConfig:
    name: str
    table_name: str
    primary_key: Union[str, list[str]]
    data_selector: str
    path_template: str  # Template with {account_id} placeholder
    method: str = "GET"
    params: Optional[dict[str, Any]] = None
    json_body_template: Optional[dict[str, Any]] = None  # Template for POST body
    incremental_fields: Optional[list[dict[str, Any]]] = None
    table_format: str = "delta"
    is_stats: bool = False
    # Partitioning configuration
    partition_keys: Optional[list[str]] = None
    partition_mode: Optional[Literal["md5", "numerical", "datetime"]] = None
    partition_format: Optional[Literal["month", "day"]] = None
    partition_size: int = 1


REDDIT_ADS_CONFIG: dict[str, EndpointConfig] = {
    "campaigns": EndpointConfig(
        name="campaigns",
        table_name="campaigns",
        primary_key="id",
        data_selector="data",
        path_template="/ad_accounts/{account_id}/campaigns",
        params={"page.size": 100},
        incremental_fields=[
            {
                "label": "modified_at",
                "type": IncrementalFieldType.DateTime,
                "field": "modified_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_keys=["modified_at"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
    ),
    "ad_groups": EndpointConfig(
        name="ad_groups",
        table_name="ad_groups",
        primary_key="id",
        data_selector="data",
        path_template="/ad_accounts/{account_id}/ad_groups",
        params={"page.size": 100},
        incremental_fields=[
            {
                "label": "modified_at",
                "type": IncrementalFieldType.DateTime,
                "field": "modified_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_keys=["modified_at"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
    ),
    "ads": EndpointConfig(
        name="ads",
        table_name="ads",
        primary_key="id",
        data_selector="data",
        path_template="/ad_accounts/{account_id}/ads",
        params={"page.size": 100},
        incremental_fields=[
            {
                "label": "modified_at",
                "type": IncrementalFieldType.DateTime,
                "field": "modified_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_keys=["modified_at"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
    ),
    "campaign_metrics": EndpointConfig(
        name="campaign_metrics",
        table_name="campaign_metrics",
        primary_key=["campaign_id", "date"],
        data_selector="data.metrics",
        path_template="/ad_accounts/{account_id}/reports",
        method="POST",
        params={"page.size": 100},
        json_body_template={
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
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        is_stats=True,
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
    ),
    "ad_group_metrics": EndpointConfig(
        name="ad_group_metrics",
        table_name="ad_group_metrics",
        primary_key=["ad_group_id", "date"],
        data_selector="data.metrics",
        path_template="/ad_accounts/{account_id}/reports",
        method="POST",
        params={"page.size": 100},
        json_body_template={
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
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        is_stats=True,
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
    ),
    "ad_metrics": EndpointConfig(
        name="ad_metrics",
        table_name="ad_metrics",
        primary_key=["ad_id", "date"],
        data_selector="data.metrics",
        path_template="/ad_accounts/{account_id}/reports",
        method="POST",
        params={"page.size": 100},
        json_body_template={
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
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        is_stats=True,
        partition_keys=["date"],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
    ),
}
