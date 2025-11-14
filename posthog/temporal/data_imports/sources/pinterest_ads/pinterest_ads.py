import collections.abc
import datetime as dt
import typing
from dataclasses import dataclass

from dlt.common.normalizers.naming.snake_case import NamingConvention

from posthog.models.integration import Integration
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value, initial_datetime
from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode, SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import PinterestAdsSourceConfig
from products.data_warehouse.backend.types import IncrementalFieldType

from .client import PinterestAdsClient, ANALYTICS_WINDOW_DAYS
from .schemas import RESOURCE_SCHEMAS, PinterestAdsResource


@dataclass
class PinterestAdsSchema:
    name: str
    primary_keys: list[str]
    field_names: list[str]
    partition_keys: list[str]
    partition_mode: PartitionMode | None
    partition_format: PartitionFormat | None
    is_analytics: bool
    partition_size: int
    filter_field_names: list[tuple[str, IncrementalFieldType]] | None = None


def get_incremental_fields() -> dict[str, list[tuple[str, IncrementalFieldType]]]:
    """Get incremental fields for Pinterest Ads resources."""
    d: dict[str, list[tuple[str, IncrementalFieldType]]] = {}
    for alias, contents in RESOURCE_SCHEMAS.items():
        if "filter_field_names" not in contents:
            continue
        d[alias.value] = contents["filter_field_names"]
    return d


def get_schemas() -> dict[str, PinterestAdsSchema]:
    """Get Pinterest Ads schemas."""
    schemas: dict[str, PinterestAdsSchema] = {}

    for _, resource_contents in RESOURCE_SCHEMAS.items():
        resource_name = resource_contents["resource_name"]
        field_names = resource_contents["field_names"].copy()
        primary_keys = resource_contents.get("primary_key", [])
        filter_field_names = resource_contents.get("filter_field_names", None)
        partition_keys = resource_contents.get("partition_keys", [])
        partition_mode = resource_contents.get("partition_mode", None)
        partition_format = resource_contents.get("partition_format", None)
        is_analytics = resource_contents.get("is_analytics", False)
        partition_size = resource_contents.get("partition_size", 1)

        schema = PinterestAdsSchema(
            name=resource_name,
            primary_keys=primary_keys,
            field_names=field_names,
            partition_keys=partition_keys,
            partition_mode=partition_mode,
            partition_format=partition_format,
            is_analytics=is_analytics,
            filter_field_names=filter_field_names,
            partition_size=partition_size,
        )

        schemas[resource_name] = schema

    return schemas


def pinterest_ads_client(config: PinterestAdsSourceConfig, team_id: int) -> PinterestAdsClient:
    """Initialize a Pinterest Ads client with provided config."""
    integration = Integration.objects.get(id=config.pinterest_ads_integration_id, team_id=team_id)
    if not integration.access_token:
        raise ValueError("Pinterest Ads integration does not have an access token")
    return PinterestAdsClient(integration.access_token)


def _convert_timestamp_to_date(timestamp: int) -> str:
    """Convert Unix timestamp to YYYY-MM-DD format."""
    return dt.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


def _convert_timestamp_fields(row: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Convert timestamp fields to datetime format for entity resources."""
    timestamp_fields = ["created_time", "updated_time", "start_time", "end_time"]
    for field in timestamp_fields:
        if field in row and row[field] is not None:
            try:
                row[field] = dt.datetime.fromtimestamp(row[field])
            except (ValueError, TypeError):
                pass
    return row


def pinterest_ads_source(
    config: PinterestAdsSourceConfig,
    resource_name: str,
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: typing.Any = None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    """A data warehouse Pinterest Ads source.

    Uses the Pinterest Marketing API to query for the configured resource and
    yields batches of records as list[dict].
    """
    name = NamingConvention().normalize_identifier(resource_name)
    schema = get_schemas()[resource_name]

    def get_rows() -> collections.abc.Iterator[list[dict]]:
        client = pinterest_ads_client(config, team_id)
        resource = PinterestAdsResource(resource_name)

        updated_since = None
        start_date = None
        end_date = None

        if schema.is_analytics:
            now = dt.datetime.now()
            end_date_dt = now - dt.timedelta(days=1)
            end_date = end_date_dt.strftime("%Y-%m-%d")

            if should_use_incremental_field and incremental_field and incremental_field_type:
                if db_incremental_field_last_value is None:
                    last_value: int | dt.datetime | dt.date | str = incremental_type_to_initial_value(
                        incremental_field_type
                    )
                else:
                    last_value = db_incremental_field_last_value

                if isinstance(last_value, dt.datetime):
                    start_date = last_value.strftime("%Y-%m-%d")
                elif isinstance(last_value, dt.date):
                    start_date = last_value.isoformat()
                elif isinstance(last_value, str):
                    start_date = last_value
            else:
                start_date_dt = max(now - dt.timedelta(days=ANALYTICS_WINDOW_DAYS), initial_datetime)
                start_date = start_date_dt.strftime("%Y-%m-%d")

            data_pages = client.get_data_by_resource(
                resource=resource,
                ad_account_id=config.ad_account_id,
                start_date=start_date,
                end_date=end_date,
            )
        else:
            if should_use_incremental_field and incremental_field and incremental_field_type:
                if db_incremental_field_last_value is not None:
                    if isinstance(db_incremental_field_last_value, dt.datetime):
                        updated_since = int(db_incremental_field_last_value.timestamp())
                    elif isinstance(db_incremental_field_last_value, (int, float)):
                        updated_since = int(db_incremental_field_last_value)

            data_pages = client.get_data_by_resource(
                resource=resource, ad_account_id=config.ad_account_id, updated_since=updated_since
            )

        for page in data_pages:
            if not schema.is_analytics:
                page = [_convert_timestamp_fields(row) for row in page]
            yield page

    return SourceResponse(
        items=get_rows(),
        name=name,
        primary_keys=schema.primary_keys,
        partition_keys=schema.partition_keys,
        partition_mode=schema.partition_mode,
        partition_format=schema.partition_format,
        partition_size=schema.partition_size,
    )
