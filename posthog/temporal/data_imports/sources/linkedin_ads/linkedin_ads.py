"""LinkedIn Ads data source with improved architecture.

This module provides the main entry point for LinkedIn Ads data imports
using a clean service-oriented architecture.
"""

import datetime as dt
from typing import Optional

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.warehouse.types import IncrementalFieldType

from .service import LinkedinAdsService
from .utils.schemas import ENDPOINTS, INCREMENTAL_FIELDS
from .utils.types import ConfigType, IncrementalValue


def get_incremental_fields() -> dict[str, list[tuple[str, IncrementalFieldType]]]:
    """Get incremental fields for LinkedIn Ads resources.

    Returns:
        Dictionary mapping endpoint names to lists of (field_name, field_type) tuples
    """
    return {
        endpoint: [(field["field"], field["field_type"]) for field in fields]
        for endpoint, fields in INCREMENTAL_FIELDS.items()
    }


def get_schemas() -> dict[str, dict]:
    """Get available schemas/endpoints for LinkedIn Ads.

    Returns:
        Dictionary mapping endpoint names to empty schema objects
    """
    return {endpoint: {} for endpoint in ENDPOINTS}


def linkedin_ads_source(
    config: ConfigType,
    resource_name: str,
    team_id: int,
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
    db_incremental_field_last_value: IncrementalValue = None,
    last_modified_since: Optional[dt.datetime] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    sync_frequency_interval: Optional[dt.timedelta] = None,
) -> SourceResponse:
    """Main function to fetch LinkedIn Ads data using the service layer.

    Args:
        config: LinkedinAdsSourceConfig object containing account_id and integration_id
        resource_name: Name of the resource to fetch (e.g., 'campaigns', 'analytics')
        team_id: PostHog team ID
        should_use_incremental_field: Whether to use incremental sync
        incremental_field: Field name for incremental sync
        incremental_field_type: Field type for incremental sync
        db_incremental_field_last_value: Last value for incremental sync
        last_modified_since: Filter data modified since this datetime
        date_start: Start date for analytics data (YYYY-MM-DD format)
        date_end: End date for analytics data (YYYY-MM-DD format)
        sync_frequency_interval: Sync frequency interval to limit incremental lookback period

    Returns:
        SourceResponse object containing the fetched data and metadata

    Raises:
        ValueError: If required configuration is missing
        Exception: If data fetching fails
    """
    # Initialize service with configuration and team ID
    service = LinkedinAdsService(config, team_id)

    # Delegate to service layer for data fetching
    return service.fetch_data(
        resource_name=resource_name,
        should_use_incremental_field=should_use_incremental_field,
        incremental_field=incremental_field,
        incremental_field_type=incremental_field_type,
        db_incremental_field_last_value=db_incremental_field_last_value,
        last_modified_since=last_modified_since,
        date_start=date_start,
        date_end=date_end,
        sync_frequency_interval=sync_frequency_interval
    )
