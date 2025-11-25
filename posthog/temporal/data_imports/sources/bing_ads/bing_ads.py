import typing
import datetime as dt
import collections.abc
from dataclasses import dataclass

import structlog
from dlt.common.normalizers.naming.snake_case import NamingConvention

from posthog.settings import integrations
from posthog.temporal.data_imports.pipelines.helpers import initial_datetime
from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode, SourceResponse

from products.data_warehouse.backend.types import IncrementalFieldType

from .client import BingAdsClient
from .schemas import RESOURCE_SCHEMAS, BingAdsResource
from .utils import fetch_data_in_yearly_chunks

logger = structlog.get_logger()


@dataclass
class BingAdsSchema:
    name: str
    primary_keys: list[str]
    field_names: list[str]
    partition_keys: list[str]
    partition_mode: PartitionMode | None
    partition_format: PartitionFormat | None
    is_stats: bool
    partition_size: int
    filter_field_names: list[tuple[str, IncrementalFieldType]] | None = None


def get_incremental_fields() -> dict[str, list[tuple[str, IncrementalFieldType]]]:
    result: dict[str, list[tuple[str, IncrementalFieldType]]] = {}
    for _resource, contents in RESOURCE_SCHEMAS.items():
        if "filter_field_names" in contents:
            result[contents["resource_name"]] = contents["filter_field_names"]
    return result


def get_schemas() -> dict[str, BingAdsSchema]:
    schemas: dict[str, BingAdsSchema] = {}

    for _, resource_contents in RESOURCE_SCHEMAS.items():
        schema = BingAdsSchema(
            name=resource_contents["resource_name"],
            primary_keys=resource_contents.get("primary_key", []),
            field_names=resource_contents["field_names"].copy(),
            partition_keys=resource_contents.get("partition_keys", []),
            partition_mode=resource_contents.get("partition_mode", None),
            partition_format=resource_contents.get("partition_format", None),
            is_stats=resource_contents.get("is_stats", False),
            filter_field_names=resource_contents.get("filter_field_names", None),
            partition_size=resource_contents.get("partition_size", 1),
        )
        schemas[schema.name] = schema

    return schemas


def bing_ads_source(
    account_id: str,
    resource_name: str,
    access_token: str,
    refresh_token: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: typing.Any = None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    name = NamingConvention().normalize_identifier(resource_name)
    schema = get_schemas()[resource_name]

    # Define generator function for lazy evaluation - dlt will call this when ready to fetch data
    def get_rows() -> collections.abc.Iterator[list[dict]]:
        developer_token = integrations.BING_ADS_DEVELOPER_TOKEN
        if not developer_token:
            raise ValueError("Bing Ads developer token not configured")

        client = BingAdsClient(
            access_token=access_token,
            refresh_token=refresh_token,
            developer_token=developer_token,
        )
        resource = BingAdsResource(resource_name)

        today = dt.date.today()
        account_id_int = int(account_id)

        if schema.is_stats:
            if should_use_incremental_field:
                if incremental_field is None or incremental_field_type is None:
                    raise ValueError("incremental_field and incremental_field_type required for incremental sync")

                is_first_sync = db_incremental_field_last_value is None

                if is_first_sync:
                    start_date = today - dt.timedelta(days=365 * 5)
                else:
                    last_value = db_incremental_field_last_value

                    if isinstance(last_value, dt.datetime):
                        start_date = last_value.date()
                    elif isinstance(last_value, dt.date):
                        start_date = last_value
                    elif isinstance(last_value, str):
                        start_date = dt.datetime.fromisoformat(last_value).date()
                    else:
                        start_date = initial_datetime.date()

                yield from fetch_data_in_yearly_chunks(
                    client=client,
                    resource=resource,
                    account_id=account_id_int,
                    start_date=start_date,
                    end_date=today,
                )
            else:
                start_date = today - dt.timedelta(days=365 * 5)
                yield from fetch_data_in_yearly_chunks(
                    client=client,
                    resource=resource,
                    account_id=account_id_int,
                    start_date=start_date,
                    end_date=today,
                )
        else:
            data_pages = client.get_data_by_resource(
                resource=resource,
                account_id=account_id_int,
                start_date=None,
                end_date=None,
            )
            for page in data_pages:
                if page:
                    yield page

    # Pass the function itself (not called) - dlt will invoke it for lazy data fetching
    return SourceResponse(
        name=name,
        items=get_rows,
        partition_mode=schema.partition_mode,
        partition_keys=schema.partition_keys,
        primary_keys=schema.primary_keys,
        partition_format=schema.partition_format,
        partition_size=schema.partition_size,
    )
