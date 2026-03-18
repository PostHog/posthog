import typing
import datetime as dt
import collections.abc
from dataclasses import dataclass

from dlt.common.normalizers.naming.snake_case import NamingConvention

from posthog.models.integration import Integration
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value, initial_datetime
from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode, SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig

from products.data_warehouse.backend.types import IncrementalFieldType

from .client import LinkedinAdsClient, LinkedinAdsResource
from .schemas import FLOAT_FIELDS, RESOURCE_SCHEMAS, URN_COLUMNS, VIRTUAL_COLUMN_URN_MAPPING


@dataclass
class LinkedinAdsSchema:
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
    """Get incremental fields for LinkedIn Ads resources."""
    d: dict[str, list[tuple[str, IncrementalFieldType]]] = {}
    for alias, contents in RESOURCE_SCHEMAS.items():
        if "filter_field_names" not in contents:
            continue
        d[alias.value] = contents["filter_field_names"]
    return d


def _extract_type_and_id_from_urn(urn: str) -> tuple[str, int] | None:
    """Extract ID from LinkedIn URN.

    Args:
        urn: LinkedIn URN like "urn:li:sponsoredCampaign:12345678"

    Returns:
        Tuple of type and integer ID or None if not found
    """
    _, _, urn_type, id_str = urn.split(":")
    return urn_type, int(id_str)


def get_schemas() -> dict[str, LinkedinAdsSchema]:
    """Get LinkedIn Ads schemas."""
    schemas: dict[str, LinkedinAdsSchema] = {}

    for _, resource_contents in RESOURCE_SCHEMAS.items():
        resource_name = resource_contents["resource_name"]
        field_names = resource_contents["field_names"].copy()
        primary_keys = resource_contents.get("primary_key", [])
        filter_field_names = resource_contents.get("filter_field_names", None)
        partition_keys = resource_contents.get("partition_keys", [])
        partition_mode = resource_contents.get("partition_mode", None)
        partition_format = resource_contents.get("partition_format", None)
        is_stats = resource_contents.get("is_stats", False)
        partition_size = resource_contents.get("partition_size", 1)

        schema = LinkedinAdsSchema(
            name=resource_name,
            primary_keys=primary_keys,
            field_names=field_names,
            partition_keys=partition_keys,
            partition_mode=partition_mode,
            partition_format=partition_format,
            is_stats=is_stats,
            filter_field_names=filter_field_names,
            partition_size=partition_size,
        )

        schemas[resource_name] = schema

    return schemas


def linkedin_ads_client(config: LinkedinAdsSourceConfig, team_id: int) -> LinkedinAdsClient:
    """Initialize a LinkedIn Ads client with provided config."""
    integration = Integration.objects.get(id=config.linkedin_ads_integration_id, team_id=team_id)
    if not integration.access_token:
        raise ValueError("LinkedIn Ads integration does not have an access token")
    return LinkedinAdsClient(integration.access_token)


def linkedin_ads_source(
    config: LinkedinAdsSourceConfig,
    resource_name: str,
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: typing.Any = None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    """A data warehouse LinkedIn Ads source.

    Uses the LinkedIn Marketing API to query for the configured resource and
    yields batches of records as list[dict].
    """
    name = NamingConvention().normalize_identifier(resource_name)
    schema = get_schemas()[resource_name]

    def get_rows() -> collections.abc.Iterator[list[dict]]:
        client = linkedin_ads_client(config, team_id)
        resource = LinkedinAdsResource(resource_name)

        # Determine date range for analytics resources
        now = dt.datetime.now()
        date_start = None
        date_end = now.strftime("%Y-%m-%d")

        if should_use_incremental_field and schema.filter_field_names:
            if incremental_field is None or incremental_field_type is None:
                raise ValueError("incremental_field and incremental_field_type can't be None")

            if db_incremental_field_last_value is None:
                last_value: int | dt.datetime | dt.date | str = incremental_type_to_initial_value(
                    incremental_field_type
                )
            else:
                last_value = db_incremental_field_last_value

            if isinstance(last_value, dt.datetime):
                date_start = last_value.strftime("%Y-%m-%d")
            elif isinstance(last_value, dt.date):
                date_start = last_value.isoformat()
            elif isinstance(last_value, str):
                date_start = last_value

        else:
            start_date = initial_datetime
            date_start = start_date.strftime("%Y-%m-%d")

        data_pages = client.get_data_by_resource(
            resource=resource,
            account_id=config.account_id,
            date_start=date_start,
            date_end=date_end,
        )

        # Process each page
        for page in data_pages:
            flattened_records = []
            for record in page:
                flattened_record = _flatten_linkedin_record(record, schema)
                flattened_records.append(flattened_record)

            yield flattened_records

    return SourceResponse(
        name=name,
        items=get_rows,
        primary_keys=schema.primary_keys,
        partition_count=1,  # this enables partitioning
        partition_size=schema.partition_size,  # this enables partitioning
        partition_mode=schema.partition_mode,
        partition_format=schema.partition_format,
        partition_keys=schema.partition_keys,
    )


def _convert_date_object_to_date(date_obj: dict[str, int] | None) -> dt.date | None:
    """Convert LinkedIn date object to Python date."""
    if isinstance(date_obj, dict) and all(k in date_obj for k in ["year", "month", "day"]):
        return dt.date(date_obj["year"], date_obj["month"], date_obj["day"])
    return None


def _convert_timestamp_to_date(last_modified: dict[str, int] | None) -> dt.date | None:
    """Convert LinkedIn timestamp (milliseconds) to date."""
    transformed_date = None
    if isinstance(last_modified, dict):
        timestamp = last_modified.get("time")
        if timestamp and isinstance(timestamp, int):
            transformed_date = dt.datetime.fromtimestamp(timestamp / 1000).date()
        else:
            transformed_date = None
    return transformed_date


def _flatten_linkedin_record(
    record: dict[str, typing.Any],
    schema: LinkedinAdsSchema,
) -> dict[str, typing.Any]:
    """Flatten a LinkedIn API record to match schema."""
    flattened: dict[str, typing.Any] = {}

    for field_name in schema.field_names:
        # Handle special virtual columns
        if field_name == "dateRange":
            date_range = record.get("dateRange", {})
            start_date_obj = date_range.get("start") if isinstance(date_range, dict) else None
            end_date_obj = date_range.get("end") if isinstance(date_range, dict) else None

            # add date_start and date_end virtual columns from dateRange
            flattened["date_start"] = _convert_date_object_to_date(start_date_obj)
            flattened["date_end"] = _convert_date_object_to_date(end_date_obj)

        elif field_name == "changeAuditStamps":
            change_audit_stamps = record.get("changeAuditStamps", {})
            created_time = None
            last_modified_time = None

            if isinstance(change_audit_stamps, dict):
                created = change_audit_stamps.get("created", {})
                created_time = _convert_timestamp_to_date(created)

                last_modified = change_audit_stamps.get("lastModified", {})
                last_modified_time = _convert_timestamp_to_date(last_modified)

            # add created_time and last_modified_time virtual columns from changeAuditStamps
            flattened["created_time"] = created_time
            flattened["last_modified_time"] = last_modified_time

        elif field_name in URN_COLUMNS:
            urn_value = record.get(field_name)
            extracted_id: int | None = None
            virtual_column_name = None
            if urn_value:
                urn_result = _extract_type_and_id_from_urn(urn_value)
                if urn_result:
                    urn_type, extracted_id = urn_result
                    virtual_column_name = VIRTUAL_COLUMN_URN_MAPPING.get(urn_type)

            # add id virtual column
            if virtual_column_name:
                flattened[virtual_column_name] = extracted_id

        # Handle virtual columns that derive from pivot values
        if field_name == "pivotValues":
            for pivot_value in record.get("pivotValues", []):
                if isinstance(pivot_value, str):
                    pivot_result = _extract_type_and_id_from_urn(pivot_value)
                    if pivot_result:
                        pivot_type, pivot_extracted_id = pivot_result
                        pivot_name = VIRTUAL_COLUMN_URN_MAPPING.get(pivot_type)

                        # add each pivot_name virtual column from pivotValues
                        if pivot_name:
                            flattened[pivot_name] = pivot_extracted_id

        value = record.get(field_name)

        # Convert based on field type
        if value is not None:
            if field_name in FLOAT_FIELDS:
                value = float(value)

        flattened[field_name] = value

    return flattened
