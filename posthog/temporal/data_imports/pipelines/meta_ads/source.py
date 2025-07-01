import collections.abc
import datetime as dt
import json
import typing
from typing import Any

import requests
from dlt.common.normalizers.naming.snake_case import NamingConvention

from posthog.exceptions_capture import capture_exception
from posthog.models import Integration
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.source import config
from posthog.warehouse.types import IncrementalFieldType
from posthog.temporal.data_imports.pipelines.meta_ads.schemas import RESOURCE_SCHEMAS


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


# Resource mapping for API endpoints
RESOURCE_ENDPOINTS = {
    "campaign": "campaigns",
    "adset": "adsets",
    "ad": "ads",
    "creative": "adcreatives",
    "account": "",  # Account is accessed directly
}


def get_incremental_fields() -> dict[str, list[tuple[str, IncrementalFieldType]]]:
    """Get incremental field configuration for Meta Ads resources."""
    incremental_fields = {}

    # Only stats resources support incremental sync
    for resource_name in ["ad_stats", "adset_stats", "campaign_stats"]:
        incremental_fields[resource_name] = [("date_start", IncrementalFieldType.Date)]

    return incremental_fields


def get_schemas(config: MetaAdsSourceConfig, team_id: int) -> dict[str, MetaAdsSchema]:
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


def meta_ads_source(
    config: MetaAdsSourceConfig,
    team_id: int,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: typing.Any = None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    """A data warehouse Meta Ads source.
    We utilize the Facebook Business SDK to query for the configured resource and
    yield batches of rows as Python lists.
    """
    name = NamingConvention().normalize_identifier(config.resource_name)
    schema = get_schemas(config, team_id)[config.resource_name]

    if schema.requires_filter and not should_use_incremental_field:
        should_use_incremental_field = True
        incremental_field = "date_start"
        incremental_field_type = IncrementalFieldType.Date

    def get_rows() -> collections.abc.Iterator[list[dict]]:
        integration = get_integration(config, team_id)
        access_token = integration.access_token

        # Determine date range for incremental sync
        date_preset = None
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
                start_date = last_value.strftime("%Y-%m-%d")
                end_date = dt.date.today().strftime("%Y-%m-%d")
                time_range = {
                    "since": start_date,
                    "until": end_date,
                }
        else:
            # Default to last 30 days for stats resources
            if schema.requires_filter:
                date_preset = "last_30d"

        # Get data based on resource type
        if config.resource_name.endswith("_stats"):
            yield from _get_insights_data(config.account_id, schema, time_range, date_preset, access_token, logger)
        else:
            yield from _get_resource_data(config.account_id, schema, config.resource_name, access_token, logger)

    return SourceResponse(
        name=name,
        items=get_rows(),
        primary_keys=schema.primary_key,
        partition_count=1 if schema.requires_filter else None,
        partition_size=1 if schema.requires_filter else None,
        partition_mode="datetime" if schema.requires_filter else None,
        partition_format="day" if schema.requires_filter else None,
        partition_keys=["date_start"] if schema.requires_filter else None,
    )


def _get_insights_data(
    account_id: str,
    schema: MetaAdsSchema,
    time_range: dict | None,
    date_preset: str | None,
    access_token: str,
    logger: FilteringBoundLogger,
) -> collections.abc.Generator[list[dict], None, None]:
    """Get insights data from Meta Ads API."""
    # Define which fields are insights metrics vs regular fields
    insights_fields = [
        field
        for field in schema.field_names
        if field
        in {
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
    regular_fields = [field for field in schema.field_names if field not in insights_fields]

    # Base resource mapping
    resource_map = {
        "ad_stats": "ads",
        "adset_stats": "adsets",
        "campaign_stats": "campaigns",
    }

    base_resource = resource_map.get(schema.name, "ads")

    params = {
        "fields": ",".join(insights_fields) if insights_fields else "impressions,clicks,spend",
        "level": base_resource[:-1],  # Remove 's' from end
        "time_increment": 1,  # Daily breakdown
    }

    if time_range:
        params["time_range"] = json.dumps(time_range)
    elif date_preset:
        params["date_preset"] = date_preset

    try:
        url = f"https://graph.facebook.com/v21.0/{account_id}/insights"
        data = _make_api_request(url, params, access_token)

        rows = []
        for insight in data.get("data", []):
            row_data = {}

            # Add insights metrics
            for field in insights_fields:
                value = insight.get(field)
                row_data[field] = _serialize_value(value)

            # Add regular fields (id, account_id, etc.)
            for field in regular_fields:
                if field == "account_id":
                    row_data[field] = account_id
                elif field in ["id", "adset_id", "campaign_id"]:
                    row_data[field] = insight.get(field)
                elif field in ["date_start", "date_stop"]:
                    row_data[field] = insight.get(field)
                else:
                    row_data[field] = None

            rows.append(row_data)

            # Yield batch when we have enough rows
            if len(rows) >= 1000:
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
        endpoint = RESOURCE_ENDPOINTS.get(resource_name)
        if endpoint is None:
            raise ValueError(f"Unknown resource: {resource_name}")

        if resource_name == "account":
            url = f"https://graph.facebook.com/v21.0/{account_id}"
        else:
            url = f"https://graph.facebook.com/v21.0/{account_id}/{endpoint}"

        params = {"fields": ",".join(field_names)} if field_names else {}
        data = _make_api_request(url, params, access_token)

        # Handle single account response vs list response
        if resource_name == "account":
            resources = [data]
        else:
            resources = data.get("data", [])

        rows = []
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
