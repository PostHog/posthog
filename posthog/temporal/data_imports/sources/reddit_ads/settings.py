from dataclasses import dataclass
from typing import Any, Optional, Union

from posthog.warehouse.types import IncrementalFieldType


@dataclass
class IncrementalField:
    label: str
    type: IncrementalFieldType
    field: str
    field_type: IncrementalFieldType


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
    incremental_fields: Optional[list[IncrementalField]] = None
    table_format: str = "delta"
    is_stats: bool = False


REDDIT_ADS_CONFIG: dict[str, EndpointConfig] = {
    "campaigns": EndpointConfig(
        name="campaigns",
        table_name="campaigns",
        primary_key="id",
        data_selector="data",
        path_template="/ad_accounts/{account_id}/campaigns",
        params={"page.size": 100},
        incremental_fields=[
            IncrementalField(
                label="modified_at",
                type=IncrementalFieldType.DateTime,
                field="modified_at",
                field_type=IncrementalFieldType.DateTime,
            )
        ],
    ),
    "ad_groups": EndpointConfig(
        name="ad_groups",
        table_name="ad_groups",
        primary_key="id",
        data_selector="data",
        path_template="/ad_accounts/{account_id}/ad_groups",
        params={"page.size": 100},
        incremental_fields=[
            IncrementalField(
                label="modified_at",
                type=IncrementalFieldType.DateTime,
                field="modified_at",
                field_type=IncrementalFieldType.DateTime,
            )
        ],
    ),
    "ads": EndpointConfig(
        name="ads",
        table_name="ads",
        primary_key="id",
        data_selector="data",
        path_template="/ad_accounts/{account_id}/ads",
        params={"page.size": 100},
        incremental_fields=[
            IncrementalField(
                label="modified_at",
                type=IncrementalFieldType.DateTime,
                field="modified_at",
                field_type=IncrementalFieldType.DateTime,
            )
        ],
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
                "fields": ["CAMPAIGN_ID", "DATE", "IMPRESSIONS", "CLICKS", "SPEND"],
                "starts_at": None,  # Will be set dynamically
                "ends_at": None,  # Will be set dynamically
                "time_zone_id": "UTC",
            }
        },
        incremental_fields=[
            IncrementalField(
                label="date",
                type=IncrementalFieldType.Date,
                field="date",
                field_type=IncrementalFieldType.Date,
            )
        ],
        is_stats=True,
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
                "fields": ["AD_GROUP_ID", "DATE", "IMPRESSIONS", "CLICKS", "SPEND"],
                "starts_at": None,  # Will be set dynamically
                "ends_at": None,  # Will be set dynamically
                "time_zone_id": "UTC",
            }
        },
        incremental_fields=[
            IncrementalField(
                label="date",
                type=IncrementalFieldType.Date,
                field="date",
                field_type=IncrementalFieldType.Date,
            )
        ],
        is_stats=True,
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
                "fields": ["AD_ID", "DATE", "IMPRESSIONS", "CLICKS", "SPEND"],
                "starts_at": None,  # Will be set dynamically
                "ends_at": None,  # Will be set dynamically
                "time_zone_id": "UTC",
            }
        },
        incremental_fields=[
            IncrementalField(
                label="date",
                type=IncrementalFieldType.Date,
                field="date",
                field_type=IncrementalFieldType.Date,
            )
        ],
        is_stats=True,
    ),
}

REDDIT_ADS_ENDPOINTS = list(REDDIT_ADS_CONFIG.keys())

REDDIT_ADS_INCREMENTAL_FIELDS = {
    endpoint: config.incremental_fields or [] for endpoint, config in REDDIT_ADS_CONFIG.items()
}
