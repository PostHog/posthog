import collections.abc
import datetime as dt
import json
import typing
from typing import Any

import pyarrow as pa
import requests
from dlt.common.normalizers.naming.snake_case import NamingConvention

from posthog.exceptions_capture import capture_exception
from posthog.models import Integration
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.meta_ads.schemas import RESOURCE_SCHEMAS
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.source import config
from posthog.temporal.data_imports.pipelines.source.sql import Column, Table
from posthog.warehouse.types import IncrementalFieldType


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


class MetaAdsColumn(Column):
    """Represents a column of a Meta Ads resource."""

    def __init__(self, name: str, data_type: str):
        self.name = name
        self.data_type = data_type

    def to_arrow_field(self):
        """Return the Arrow type associated with this column."""
        arrow_type: pa.DataType

        match self.data_type:
            case "string":
                arrow_type = pa.string()
            case "integer":
                arrow_type = pa.int64()
            case "float":
                arrow_type = pa.float64()
            case "boolean":
                arrow_type = pa.bool_()
            case "datetime":
                arrow_type = pa.timestamp("us")
            case "date":
                arrow_type = pa.date32()
            case "json":
                arrow_type = pa.string()  # Store JSON as string
            case _:
                arrow_type = pa.string()  # Default to string

        return pa.field(self.name, arrow_type)


class MetaAdsTable(Table[MetaAdsColumn]):
    def __init__(self, *args, requires_filter: bool, primary_key: list[str], **kwargs):
        self.requires_filter = requires_filter
        self.primary_key = primary_key
        super().__init__(*args, **kwargs)


TableSchemas = dict[str, MetaAdsTable]


def _infer_column_type(field_name: str) -> str:
    """Infer column type based on field name."""
    if field_name in ["id", "account_id", "adset_id", "campaign_id"]:
        return "string"
    elif field_name in ["impressions", "clicks", "reach", "unique_clicks"]:
        return "integer"
    elif field_name in [
        "spend",
        "cpm",
        "cpc",
        "ctr",
        "cpp",
        "frequency",
        "bid_amount",
        "daily_budget",
        "lifetime_budget",
        "budget_remaining",
        "amount_spent",
        "balance",
        "spend_cap",
    ]:
        return "float"
    elif field_name in ["created_time", "updated_time", "start_time", "end_time", "stop_time"]:
        return "datetime"
    elif field_name in ["date_start", "date_stop"]:
        return "date"
    elif field_name in [
        "actions",
        "conversions",
        "conversion_values",
        "cost_per_action_type",
        "targeting",
        "promoted_object",
        "creative",
        "tracking_specs",
        "conversion_specs",
        "special_ad_categories",
        "funding_source_details",
    ]:
        return "json"
    else:
        return "string"


def get_incremental_fields() -> dict[str, list[tuple[str, IncrementalFieldType]]]:
    """Get incremental field configuration for Meta Ads resources."""
    d = {}
    for alias, contents in RESOURCE_SCHEMAS.items():
        assert isinstance(contents, dict)

        if "filter_field_names" not in contents:
            continue

        d[alias] = contents["filter_field_names"]

    return d


def get_schemas(config: MetaAdsSourceConfig, team_id: int) -> TableSchemas:
    """Obtain Meta Ads schemas."""
    table_schemas = {}

    for table_alias, resource_contents in RESOURCE_SCHEMAS.items():
        assert isinstance(resource_contents, dict)

        resource_name = resource_contents["resource_name"]
        assert isinstance(resource_name, str)

        field_names = resource_contents["field_names"]
        requires_filter = resource_contents.get("filter_field_names", None) is not None
        primary_key = typing.cast(list[str], resource_contents.get("primary_key", []))

        columns = []

        for field_name in field_names:
            assert isinstance(field_name, str)

            data_type = _infer_column_type(field_name)
            columns.append(MetaAdsColumn(name=field_name, data_type=data_type))

        table = MetaAdsTable(
            name=resource_name,
            alias=table_alias,
            requires_filter=requires_filter,
            primary_key=primary_key,
            columns=columns,
            parents=None,
        )
        table_schemas[table_alias] = table

    return table_schemas


def _serialize_complex_field(value: Any) -> Any:
    """Serialize complex fields (lists, dicts) to JSON strings."""
    if value is None:
        return None
    elif isinstance(value, dict | list):
        return json.dumps(value)
    else:
        return value


def _make_api_request(url: str, params: dict, access_token: str) -> dict:
    """Make a request to the Meta Graph API."""
    params["access_token"] = access_token
    response = requests.get(url, params=params)

    if response.status_code != 200:
        raise Exception(f"Meta API request failed: {response.status_code} - {response.text}")

    return response.json()


def _get_insights_fields(field_names: list[str]) -> list[str]:
    """Get fields that should be requested from insights API."""
    insights_fields = [
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
    ]
    return [field for field in field_names if field in insights_fields]


def _get_regular_fields(field_names: list[str]) -> list[str]:
    """Get fields that should be requested from regular API."""
    insights_fields = [
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
        "date_start",
        "date_stop",
    ]
    return [field for field in field_names if field not in insights_fields]


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
    yield batches of rows as Arrow tables.
    """
    name = NamingConvention().normalize_identifier(config.resource_name)
    table = get_schemas(config, team_id)[config.resource_name]

    if table.requires_filter and not should_use_incremental_field:
        should_use_incremental_field = True
        incremental_field = "date_start"
        incremental_field_type = IncrementalFieldType.Date

    def get_rows() -> collections.abc.Iterator[pa.Table]:
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
            if table.requires_filter:
                date_preset = "last_30d"

        # Get data based on resource type
        if config.resource_name.endswith("_stats"):
            yield from _get_insights_data(config.account_id, table, time_range, date_preset, access_token, logger)
        else:
            yield from _get_resource_data(config.account_id, table, config.resource_name, access_token, logger)

    return SourceResponse(
        name=name,
        items=get_rows(),
        primary_keys=table.primary_key,
        partition_count=1 if table.requires_filter else None,
        partition_size=1 if table.requires_filter else None,
        partition_mode="datetime" if table.requires_filter else None,
        partition_format="day" if table.requires_filter else None,
        partition_keys=["date_start"] if table.requires_filter else None,
    )


def _get_insights_data(
    account_id: str,
    table: MetaAdsTable,
    time_range: dict | None,
    date_preset: str | None,
    access_token: str,
    logger: FilteringBoundLogger,
) -> collections.abc.Generator[pa.Table, None, None]:
    """Get insights data from Meta Ads API."""
    insights_fields = _get_insights_fields([col.name for col in table.columns])
    regular_fields = _get_regular_fields([col.name for col in table.columns])

    # Base resource mapping
    resource_map = {
        "ad_stats": "ads",
        "adset_stats": "adsets",
        "campaign_stats": "campaigns",
    }

    base_resource = resource_map.get(table.alias, "ads")

    params = {
        "fields": ",".join(insights_fields),
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
                row_data[field] = _serialize_complex_field(value)

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
                yield pa.Table.from_pylist(rows, schema=table.to_arrow_schema())
                rows = []

        # Yield remaining rows
        if rows:
            yield pa.Table.from_pylist(rows, schema=table.to_arrow_schema())

    except Exception as e:
        logger.debug(f"Error fetching insights data: {e}")
        capture_exception(e)
        raise


def _get_resource_data(
    account_id: str,
    table: MetaAdsTable,
    resource_name: str,
    access_token: str,
    logger: FilteringBoundLogger,
) -> collections.abc.Generator[pa.Table, None, None]:
    """Get regular resource data from Meta Ads API."""
    field_names = [col.name for col in table.columns if col.name not in ["account_id"]]

    try:
        # Get the appropriate resource collection
        if resource_name == "campaign":
            url = f"https://graph.facebook.com/v21.0/{account_id}/campaigns"
        elif resource_name == "adset":
            url = f"https://graph.facebook.com/v21.0/{account_id}/adsets"
        elif resource_name == "ad":
            url = f"https://graph.facebook.com/v21.0/{account_id}/ads"
        elif resource_name == "creative":
            url = f"https://graph.facebook.com/v21.0/{account_id}/adcreatives"
        elif resource_name == "account":
            url = f"https://graph.facebook.com/v21.0/{account_id}"
        else:
            raise ValueError(f"Unknown resource: {resource_name}")

        params = {"fields": ",".join(field_names)}
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
                row_data[field] = _serialize_complex_field(value)

            rows.append(row_data)

            # Yield batch when we have enough rows
            if len(rows) >= 1000:
                yield pa.Table.from_pylist(rows, schema=table.to_arrow_schema())
                rows = []

        # Yield remaining rows
        if rows:
            yield pa.Table.from_pylist(rows, schema=table.to_arrow_schema())

    except Exception as e:
        logger.debug(f"Error fetching {resource_name} data: {e}")
        capture_exception(e)
        raise
