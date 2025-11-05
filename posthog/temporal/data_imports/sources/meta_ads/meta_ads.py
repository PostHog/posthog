import json
import typing
import datetime as dt
import collections.abc
from dataclasses import dataclass

import requests
from dlt.common.normalizers.naming.snake_case import NamingConvention

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, Integration, MetaAdsIntegration
from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode, SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import MetaAdsSourceConfig
from posthog.temporal.data_imports.sources.meta_ads.schemas import RESOURCE_SCHEMAS

from products.data_warehouse.backend.types import IncrementalFieldType

# Meta Ads API only supports data from the last 3 years
META_ADS_MAX_HISTORY_DAYS = 3 * 365


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


def get_integration(config: MetaAdsSourceConfig, team_id: int) -> Integration:
    """Get the Meta Ads integration."""
    integration = Integration.objects.get(id=config.meta_ads_integration_id, team_id=team_id)
    meta_ads_integration = MetaAdsIntegration(integration)
    meta_ads_integration.refresh_access_token()

    if meta_ads_integration.integration.errors == ERROR_TOKEN_REFRESH_FAILED:
        raise Exception("Failed to refresh token for Meta Ads integration. Please re-authorize the integration.")

    return meta_ads_integration.integration


@dataclass
class MetaAdsSchema:
    name: str
    primary_keys: list[str]
    field_names: list[str]
    url: str
    extra_params: dict
    partition_keys: list[str]
    partition_mode: PartitionMode
    partition_format: PartitionFormat
    is_stats: bool


# Note: can make this static but keeping schemas.py to match other schema files for now
def get_schemas() -> dict[str, MetaAdsSchema]:
    """Obtain Meta Ads schemas using predefined field definitions."""
    schemas: dict[str, MetaAdsSchema] = {}

    for resource_name, schema_def in RESOURCE_SCHEMAS.items():
        field_names = schema_def["field_names"].copy()
        primary_keys = schema_def["primary_keys"]
        url = schema_def["url"]
        extra_params = schema_def["extra_params"]
        partition_keys = schema_def["partition_keys"]
        partition_mode = schema_def["partition_mode"]
        partition_format = schema_def["partition_format"]
        is_stats = schema_def.get("is_stats", False)

        schema = MetaAdsSchema(
            name=resource_name,
            primary_keys=primary_keys,
            field_names=field_names,
            url=url,
            extra_params=extra_params,
            partition_keys=partition_keys,
            partition_mode=partition_mode,
            partition_format=partition_format,
            is_stats=is_stats,
        )

        schemas[resource_name] = schema

    return schemas


def _make_paginated_api_request(
    url: str, params: dict, access_token: str, time_range: dict | None = None
) -> collections.abc.Generator[list[dict], None, None]:
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

            response_payload = response.json()
            yield response_payload.get("data", [])

            paging = response_payload.get("paging", {})
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

                response_payload = response.json()
                yield response_payload.get("data", [])

                paging = response_payload.get("paging", {})
                next_url = paging.get("next")

            current_start = current_end + dt.timedelta(days=1)


def meta_ads_source(
    resource_name: str,
    config: MetaAdsSourceConfig,
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: typing.Any = None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    """A data warehouse Meta Ads source."""
    name = NamingConvention().normalize_identifier(resource_name)
    schema = get_schemas()[resource_name]

    def get_rows():
        integration = get_integration(config, team_id)
        access_token = integration.access_token

        if access_token is None:
            raise ValueError("Access token is required for Meta Ads integration")

        # Determine date range for incremental sync
        time_range = None

        if should_use_incremental_field:
            if incremental_field is None or incremental_field_type is None:
                raise ValueError("incremental_field and incremental_field_type can't be None")

            if db_incremental_field_last_value is None:
                last_value: dt.date = dt.date.today() - dt.timedelta(days=META_ADS_MAX_HISTORY_DAYS)
            else:
                last_value = db_incremental_field_last_value

            start_date = last_value.strftime("%Y-%m-%d")
            # Meta Ads API is day based so only import if the day is complete
            end_date = dt.date.today().strftime("%Y-%m-%d")
            time_range = {
                "since": start_date,
                "until": end_date,
            }
        elif schema.is_stats:
            time_range = {
                "since": (dt.date.today() - dt.timedelta(days=META_ADS_MAX_HISTORY_DAYS)).strftime("%Y-%m-%d"),
                "until": dt.date.today().strftime("%Y-%m-%d"),
            }

        formatted_url = schema.url.format(
            API_VERSION=MetaAdsIntegration.api_version, account_id=_clean_account_id(config.account_id)
        )
        params = {
            "fields": ",".join(schema.field_names),
            "limit": 500,
            **schema.extra_params,
        }

        yield from _make_paginated_api_request(formatted_url, params, access_token, time_range)

    return SourceResponse(
        name=name,
        items=get_rows(),
        primary_keys=schema.primary_keys,
        partition_mode=schema.partition_mode,
        partition_format=schema.partition_format,
        partition_keys=schema.partition_keys,
    )
