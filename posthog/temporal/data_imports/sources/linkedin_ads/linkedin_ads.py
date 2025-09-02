import json
import typing
import datetime as dt
import collections.abc

import pyarrow as pa
from dlt.common.normalizers.naming.snake_case import NamingConvention

from posthog.models.integration import Integration
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.sql import Column, Table
from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig
from posthog.warehouse.types import IncrementalFieldType

from .client import LINKEDIN_SPONSORED_URN_PREFIX, LinkedinAdsClient, LinkedinAdsResource
from .schemas import (
    DATE_FIELDS,
    FLOAT_FIELDS,
    INTEGER_FIELDS,
    RESOURCE_SCHEMAS,
    RESOURCE_VIRTUAL_COLUMNS,
    VIRTUAL_COLUMN_URN_MAPPING,
    VIRTUAL_COLUMNS,
)


class LinkedinAdsColumn(Column):
    """Represents a column of a LinkedIn Ads resource."""

    def __init__(self, qualified_name: str, data_type: str = "string"):
        self.name = qualified_name.replace(".", "_")
        self.qualified_name = qualified_name
        self.data_type = data_type

    def to_arrow_field(self):
        """Return the Arrow type associated with this column."""
        arrow_type: pa.DataType

        if self.qualified_name in INTEGER_FIELDS:
            arrow_type = pa.int64()
        elif self.qualified_name in FLOAT_FIELDS:
            arrow_type = pa.float64()
        elif self.qualified_name in DATE_FIELDS:
            arrow_type = pa.date32()
        else:
            # Everything else as strings
            arrow_type = pa.string()

        return pa.field(self.name, arrow_type)


def get_incremental_fields() -> dict[str, list[tuple[str, IncrementalFieldType]]]:
    """Get incremental fields for LinkedIn Ads resources."""
    d = {}
    for alias, contents in RESOURCE_SCHEMAS.items():
        assert isinstance(contents, dict)

        if "filter_field_names" not in contents:
            continue

        d[alias] = contents["filter_field_names"]

    return d


class LinkedinAdsTable(Table[LinkedinAdsColumn]):
    def __init__(self, *args, requires_filter: bool, primary_key: list[str], **kwargs):
        self.requires_filter = requires_filter
        self.primary_key = [pkey.replace(".", "_") for pkey in primary_key]
        super().__init__(*args, **kwargs)


TableSchemas = dict[str, LinkedinAdsTable]


def _extract_id_from_urn(urn: str, urn_type: str) -> int | None:
    """Extract ID from LinkedIn URN.

    Args:
        urn: LinkedIn URN like "urn:li:sponsoredCampaign:185129613"
        urn_type: Type to match like "Campaign" or "CampaignGroup"

    Returns:
        Integer ID or None if not found
    """
    if not urn or not isinstance(urn, str):
        return None

    expected_prefix = f"{LINKEDIN_SPONSORED_URN_PREFIX}{urn_type}:"
    if urn.startswith(expected_prefix):
        try:
            id_str = urn[len(expected_prefix) :]
            return int(id_str)
        except ValueError:
            return None
    return None


def get_schemas() -> TableSchemas:
    """Get LinkedIn Ads schemas.

    Unlike Google Ads, LinkedIn doesn't have dynamic schema discovery,
    so we use our predefined schemas.
    """

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
            columns.append(LinkedinAdsColumn(qualified_name=field_name))

        # Add virtual columns for partition keys if this table requires filtering
        if requires_filter and resource_contents.get("filter_field_names"):
            for filter_field_name, _ in resource_contents["filter_field_names"]:
                # Add the filter field as a virtual column for partitioning
                columns.append(LinkedinAdsColumn(qualified_name=filter_field_name))

        # Add virtual ID columns for analytics tables that have pivot values
        if "pivotValues" in field_names:
            virtual_column = RESOURCE_VIRTUAL_COLUMNS.get(resource_name)
            if virtual_column:
                columns.append(LinkedinAdsColumn(qualified_name=virtual_column))

        table = LinkedinAdsTable(
            name=resource_name,
            alias=table_alias,
            requires_filter=requires_filter,
            primary_key=primary_key,
            columns=columns,
            parents=None,
        )
        table_schemas[table_alias] = table

    return table_schemas


def linkedin_ads_client(config: LinkedinAdsSourceConfig, team_id: int) -> LinkedinAdsClient:
    """Initialize a LinkedIn Ads client with provided config."""
    integration = Integration.objects.get(id=config.linkedin_ads_integration_id, team_id=team_id)
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
    yield batches of rows as `pyarrow.Table`.
    """
    name = NamingConvention().normalize_identifier(resource_name)
    table = get_schemas()[resource_name]

    if table.requires_filter and not should_use_incremental_field:
        should_use_incremental_field = True
        incremental_field = "dateRange.start"
        incremental_field_type = IncrementalFieldType.Date

    def get_rows() -> collections.abc.Iterator[pa.Table]:
        client = linkedin_ads_client(config, team_id)
        resource = LinkedinAdsResource(resource_name)

        # Determine date range for analytics resources
        date_start = None
        date_end = None

        if should_use_incremental_field and table.requires_filter:
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

            # Set end date to today
            date_end = dt.datetime.now().strftime("%Y-%m-%d")

        elif table.requires_filter:
            # Default to last 30 days for analytics resources
            end_date = dt.datetime.now()
            start_date = end_date - dt.timedelta(days=30)
            date_start = start_date.strftime("%Y-%m-%d")
            date_end = end_date.strftime("%Y-%m-%d")

        # Get data from LinkedIn API
        data_pages = client.get_data_by_resource(
            resource=resource,
            account_id=config.account_id,
            date_start=date_start,
            date_end=date_end,
        )

        # Process each page of data
        for page in data_pages:
            yield from _data_as_arrow_table(page, table)

    return SourceResponse(
        name=name,
        items=get_rows(),
        primary_keys=table.primary_key,
        partition_count=1 if table.requires_filter else None,  # this enables partitioning
        partition_size=1 if table.requires_filter else None,  # this enables partitioning
        partition_mode="datetime" if table.requires_filter else None,
        partition_format="day" if table.requires_filter else None,
        partition_keys=["dateRange_start"] if table.requires_filter else None,
    )


def _data_as_arrow_table(
    data: list[dict],
    table: Table[LinkedinAdsColumn],
    table_size: int | None = None,
) -> collections.abc.Generator[pa.Table, None, None]:
    """Convert LinkedIn API response data to `pyarrow.Table`."""
    rows = []

    for record in data:
        # Flatten the record to match our table schema
        flattened_record = _flatten_linkedin_record(record, table)
        rows.append(flattened_record)

        if table_size is not None and len(rows) >= table_size:
            yield pa.Table.from_pylist(rows, schema=table.to_arrow_schema())
            rows = []

    if len(rows) > 0:
        yield pa.Table.from_pylist(rows, schema=table.to_arrow_schema())


def _extract_virtual_column_value(record: dict[str, typing.Any], column_name: str) -> int | None:
    """Extract virtual column values from pivot data."""
    urn_type = VIRTUAL_COLUMN_URN_MAPPING.get(column_name)
    if not urn_type:
        return None

    pivot_values = record.get("pivotValues")
    if not pivot_values:
        return None

    # Handle case where pivotValues is a JSON string
    if isinstance(pivot_values, str):
        try:
            pivot_values = json.loads(pivot_values)
        except json.JSONDecodeError:
            pivot_values = [pivot_values]  # Treat as single value

    # Extract ID from pivot values by URN type
    if not isinstance(pivot_values, list):
        return None

    return next(
        (extracted_id for urn in pivot_values if (extracted_id := _extract_id_from_urn(urn, urn_type)) is not None),
        None,
    )


def _flatten_linkedin_record(
    record: dict[str, typing.Any],
    table: Table[LinkedinAdsColumn],
) -> dict[str, typing.Any]:
    """Flatten a LinkedIn API record to match table schema."""
    flattened = {}

    for column in table.columns:
        # Handle virtual columns that derive from pivot values
        if column.qualified_name in VIRTUAL_COLUMNS:
            value = _extract_virtual_column_value(record, column.qualified_name)
        elif column.qualified_name == "dateRange.start":
            date_range = record.get("dateRange", {})
            start_date = date_range.get("start") if isinstance(date_range, dict) else None
            if isinstance(start_date, dict) and all(k in start_date for k in ["year", "month", "day"]):
                value = dt.date(start_date["year"], start_date["month"], start_date["day"])
            else:
                value = None
        else:
            # Extract value based on qualified name
            value = record.get(column.qualified_name)

            # Convert based on field type
            if value is not None:
                if column.qualified_name in DATE_FIELDS and isinstance(value, dict):
                    # Convert LinkedIn date object to Python date
                    if all(k in value for k in ["year", "month", "day"]):
                        value = dt.date(value["year"], value["month"], value["day"])
                    else:
                        value = None
                elif column.qualified_name in INTEGER_FIELDS:
                    value = int(value)
                elif column.qualified_name in FLOAT_FIELDS:
                    value = float(value)
                elif isinstance(value, dict | list):
                    value = json.dumps(value)
                else:
                    value = str(value)

        flattened[column.name] = value

    return flattened
