import collections.abc
import datetime as dt
import json
import typing
from typing import Any
from enum import StrEnum

import requests
from dlt.common.normalizers.naming.snake_case import NamingConvention

from posthog.exceptions_capture import capture_exception
from posthog.models import Integration
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.source import config
from posthog.warehouse.types import IncrementalField, IncrementalFieldType
from posthog.temporal.data_imports.pipelines.meta_ads.schemas import RESOURCE_SCHEMAS


class MetaAdsResource(StrEnum):
    Campaign = "campaign"
    CampaignStats = "campaign_stats"
    Adset = "adset"
    AdStats = "ad_stats"
    Ad = "ad"
    AdsetStats = "adset_stats"
    Creative = "creative"
    Account = "account"


# Resource mapping for API endpoints
RESOURCE_ENDPOINTS = {
    MetaAdsResource.Campaign: "campaigns",
    MetaAdsResource.Adset: "adsets",
    MetaAdsResource.Ad: "ads",
    MetaAdsResource.Creative: "adcreatives",
    MetaAdsResource.Account: "",  # Account is accessed directly
    MetaAdsResource.CampaignStats: "campaigns",
    MetaAdsResource.AdsetStats: "adsets",
    MetaAdsResource.AdStats: "ads",
}

ENDPOINTS = (
    MetaAdsResource.Campaign,
    MetaAdsResource.CampaignStats,
    MetaAdsResource.Adset,
    MetaAdsResource.AdsetStats,
    MetaAdsResource.Ad,
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


def _clean_account_id(s: str | None) -> str | None:
    """Clean account IDs from Meta Ads.
    Account IDs should have 'act_' prefix for API calls.
    """
    if not s:
        return s

    s = s.strip()
    if not s.startswith("act_"):
        s = f"act_{s}"
    return s


@config.config
class MetaAdsSourceConfig(config.Config):
    """Meta Ads source config using OAuth2 flow for authentication."""

    resource_name: str
    meta_ads_integration_id: str
    account_id: str = config.value(converter=_clean_account_id)

    @classmethod
    def from_dict(cls, data: dict) -> "MetaAdsSourceConfig":
        return cls(
            resource_name=data.get("resource_name", ""),
            meta_ads_integration_id=data.get("meta_ads_integration_id", ""),
            account_id=data.get("account_id", ""),
        )


def get_integration(config: MetaAdsSourceConfig, team_id: int) -> Integration:
    """Get the Meta Ads integration."""
    return Integration.objects.get(id=config.meta_ads_integration_id, team_id=team_id)


# Simple schema structure without typing
class MetaAdsSchema:
    def __init__(self, name: str, requires_filter: bool, primary_key: list[str], field_names: list[str]):
        self.name = name
        self.requires_filter = requires_filter
        self.primary_key = primary_key
        self.field_names = field_names


def get_schemas() -> dict[str, MetaAdsSchema]:
    """Obtain Meta Ads schemas using predefined field definitions."""
    schemas = {}

    for resource_name, schema_def in RESOURCE_SCHEMAS.items():
        field_names = schema_def["field_names"].copy()
        primary_key = schema_def["primary_key"]
        requires_filter = resource_name.endswith("_stats")

        schema = MetaAdsSchema(
            name=resource_name,
            requires_filter=requires_filter,
            primary_key=primary_key,
            field_names=field_names,
        )
        schemas[resource_name] = schema

    return schemas


def _serialize_value(value: Any) -> Any:
    """Serialize complex values to JSON strings."""
    if isinstance(value, dict | list):
        return json.dumps(value)
    return value


def _make_api_request(url: str, params: dict, access_token: str) -> dict:
    """Make a request to the Meta Graph API."""
    params["access_token"] = access_token
    response = requests.get(url, params=params)

    if response.status_code != 200:
        raise Exception(f"Meta API request failed: {response.status_code} - {response.text}")

    return response.json()


def _make_paginated_api_request(
    url: str, params: dict, access_token: str, time_range: dict | None = None
) -> collections.abc.Generator[dict, None, None]:
    """Make paginated requests to the Meta Graph API.
    This function handles two types of pagination:
    1. Standard pagination: Uses Meta's paging.next URLs to fetch all pages of results
    2. Time-range pagination: Breaks large date ranges into monthly chunks to avoid slow API sorting,
       then applies standard pagination within each monthly chunk
    """
    params["access_token"] = access_token

    if time_range is None:
        # Original pagination logic for non-time-range requests
        next_url = url
        while next_url:
            if next_url == url:
                response = requests.get(next_url, params=params)
            else:
                response = requests.get(next_url)

            if response.status_code != 200:
                raise Exception(f"Meta API request failed: {response.status_code} - {response.text}")

            data = response.json()
            yield data

            paging = data.get("paging", {})
            next_url = paging.get("next")
    else:
        start_date = dt.datetime.strptime(time_range["since"], "%Y-%m-%d")
        end_date = dt.datetime.strptime(time_range["until"], "%Y-%m-%d")

        current_start = start_date
        while current_start <= end_date:
            if current_start.month == 12:
                current_end = current_start.replace(year=current_start.year + 1, month=1, day=1) - dt.timedelta(days=1)
            else:
                current_end = current_start.replace(month=current_start.month + 1, day=1) - dt.timedelta(days=1)

            current_end = min(current_end, end_date)

            monthly_time_range = {
                "since": current_start.strftime("%Y-%m-%d"),
                "until": current_end.strftime("%Y-%m-%d"),
            }

            monthly_params = params.copy()
            monthly_params["time_range"] = json.dumps(monthly_time_range)

            next_url = url

            while next_url:
                if next_url == url:
                    response = requests.get(next_url, params=monthly_params)
                else:
                    response = requests.get(next_url)

                if response.status_code != 200:
                    raise Exception(f"Meta API request failed: {response.status_code} - {response.text}")

                data = response.json()
                yield data

                paging = data.get("paging", {})
                next_url = paging.get("next")

            current_start = current_end + dt.timedelta(days=1)


def meta_ads_source(
    config: MetaAdsSourceConfig,
    team_id: int,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: typing.Any = None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    """A data warehouse Meta Ads source."""
    name = NamingConvention().normalize_identifier(config.resource_name)
    schema = get_schemas()[config.resource_name]

    if schema.requires_filter and not should_use_incremental_field:
        should_use_incremental_field = True
        incremental_field = "date_start"
        incremental_field_type = IncrementalFieldType.Date

    def get_rows() -> collections.abc.Iterator[list[dict]]:
        integration = get_integration(config, team_id)
        access_token = integration.access_token

        # Determine date range for incremental sync
        time_range = None

        if should_use_incremental_field:
            if incremental_field is None or incremental_field_type is None:
                raise ValueError("incremental_field and incremental_field_type can't be None")

            if db_incremental_field_last_value is None:
                last_value: int | dt.datetime | dt.date | str = incremental_type_to_initial_value(
                    incremental_field_type
                )
            else:
                last_value = db_incremental_field_last_value

            if isinstance(last_value, dt.datetime | dt.date):
                # Limit to 3 years ago if last_value is older. Meta Ads API only supports 3 years filtering.
                three_years_ago = dt.date.today() - dt.timedelta(days=3 * 365)
                if isinstance(last_value, dt.datetime):
                    last_value_date = last_value.date()
                else:
                    last_value_date = last_value

                start_date = max(last_value_date, three_years_ago).strftime("%Y-%m-%d")
                end_date = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
                time_range = {
                    "since": start_date,
                    "until": end_date,
                }
        else:
            time_range = {
                "since": (dt.date.today() - dt.timedelta(days=3 * 365)).strftime("%Y-%m-%d"),
                "until": dt.date.today().strftime("%Y-%m-%d"),
            }

        # Get data based on resource type
        if config.resource_name.endswith("_stats"):
            yield from _get_insights_data(config.account_id, schema, time_range, access_token, logger)
        else:
            yield from _get_resource_data(config.account_id, schema, config.resource_name, access_token, logger)

    return SourceResponse(
        name=name,
        items=get_rows(),
        primary_keys=schema.primary_key,
        partition_count=None,
        partition_size=None,
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    )


def _get_insights_data(
    account_id: str,
    schema: MetaAdsSchema,
    time_range: dict | None,
    access_token: str,
    logger: FilteringBoundLogger,
) -> collections.abc.Generator[list[dict], None, None]:
    """Get insights data from Meta Ads API."""

    base_resource = RESOURCE_ENDPOINTS.get(MetaAdsResource(schema.name), "ads")

    insights_fields = [
        field
        for field in schema.field_names
        if field
        in {
            f"{base_resource[:-1]}_id",
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
            "video_30_sec_watched_actions",
            "video_p25_watched_actions",
            "video_p50_watched_actions",
            "video_p75_watched_actions",
            "video_p95_watched_actions",
            "video_p100_watched_actions",
        }
    ]

    params = {
        "fields": ",".join(insights_fields) if insights_fields else "impressions,clicks,spend",
        "level": base_resource[:-1],  # Remove 's' from end
        "time_increment": 1,  # Daily breakdown
        "limit": 100,
    }

    try:
        url = f"https://graph.facebook.com/v21.0/{account_id}/insights"
        rows = []

        # Use paginated API request to handle large result sets
        for page_data in _make_paginated_api_request(url, params, access_token, time_range):
            for insight in page_data.get("data", []):
                row_data = {}
                for k, v in insight.items():
                    row_data[k] = _serialize_value(v)

                rows.append(row_data)

                # Yield batch when we have enough rows
                if len(rows) >= DEFAULT_CHUNK_SIZE:
                    yield rows
                    rows = []

        # Yield remaining rows
        if rows:
            yield rows

    except Exception as e:
        logger.debug(f"Error fetching insights data: {e}")
        capture_exception(e)
        raise


def _get_resource_data(
    account_id: str,
    schema: MetaAdsSchema,
    resource_name: str,
    access_token: str,
    logger: FilteringBoundLogger,
) -> collections.abc.Generator[list[dict], None, None]:
    """Get regular resource data from Meta Ads API."""
    # Use all fields except account_id (which we'll add separately)
    field_names = [field for field in schema.field_names if field != "account_id"]

    try:
        # Get the appropriate resource collection
        endpoint = RESOURCE_ENDPOINTS.get(MetaAdsResource(resource_name))
        if endpoint is None:
            raise ValueError(f"Unknown resource: {resource_name}")

        if resource_name == "account":
            url = f"https://graph.facebook.com/v21.0/{account_id}"
        else:
            url = f"https://graph.facebook.com/v21.0/{account_id}/{endpoint}"

        params = (
            {
                "fields": ",".join(field_names),
                "limit": 100,
            }
            if field_names
            else {}
        )
        rows = []

        if resource_name == "account":
            # Account endpoint doesn't have pagination
            data = _make_api_request(url, params, access_token)
            resources = [data]

            for resource in resources:
                row_data = {"account_id": account_id}

                for field in field_names:
                    value = resource.get(field)
                    row_data[field] = _serialize_value(value)

                rows.append(row_data)

            if rows:
                yield rows
        else:
            # Use paginated API request for collection endpoints
            for page_data in _make_paginated_api_request(url, params, access_token):
                resources = page_data.get("data", [])

                for resource in resources:
                    row_data = {"account_id": account_id}

                    for field in field_names:
                        value = resource.get(field)
                        row_data[field] = _serialize_value(value)

                    rows.append(row_data)

                    # Yield batch when we have enough rows
                    if len(rows) >= 1000:
                        yield rows
                        rows = []

            # Yield remaining rows
            if rows:
                yield rows

    except Exception as e:
        logger.debug(f"Error fetching {resource_name} data: {e}")
        capture_exception(e)
        raise
