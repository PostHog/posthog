"""Service layer for LinkedIn Ads data import coordination."""

import datetime as dt
from typing import Any, Optional

import structlog

from posthog.models.integration import Integration
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.warehouse.types import IncrementalFieldType

from ..client import LinkedinAdsClient
from ..utils.date_handler import LinkedinAdsDateHandler
from ..utils.schemas import LinkedinAdsResource
from ..utils.types import ConfigType, IncrementalValue, ResourceMethodTuple
from ..utils.utils import (
    CIRCUIT_BREAKER_TIMEOUT,
    _failure_counts,
    check_circuit_breaker,
    determine_primary_keys,
    flatten_data_item,
    record_failure,
    record_success,
    validate_account_id,
)

logger = structlog.get_logger(__name__)


class LinkedinAdsService:
    """Service layer for coordinating LinkedIn Ads data imports.

    This service handles:
    - Configuration validation
    - Integration management
    - Circuit breaker logic
    - Data fetching coordination
    - Response formatting
    """

    def __init__(self, config: ConfigType, team_id: int):
        """Initialize LinkedIn Ads service.

        Args:
            config: Configuration object containing account_id and integration_id
            team_id: PostHog team ID
        """
        self.config = config
        self.team_id = team_id
        self.account_id = config.account_id
        self.integration_id = config.linkedin_ads_integration_id
        self.date_handler = LinkedinAdsDateHandler()

        # Validate configuration
        self._validate_configuration()

    def fetch_data(
        self,
        resource_name: str,
        should_use_incremental_field: bool = False,
        incremental_field: Optional[str] = None,
        incremental_field_type: Optional[IncrementalFieldType] = None,
        db_incremental_field_last_value: IncrementalValue = None,
        last_modified_since: Optional[dt.datetime] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        sync_frequency_interval: Optional[dt.timedelta] = None,
    ) -> SourceResponse:
        """Fetch data for a specific resource.

        Args:
            resource_name: Name of the resource to fetch
            should_use_incremental_field: Whether to use incremental sync
            incremental_field: Field name for incremental sync
            incremental_field_type: Field type for incremental sync
            db_incremental_field_last_value: Last value for incremental sync
            last_modified_since: Filter data modified since this datetime
            date_start: Start date for analytics data
            date_end: End date for analytics data
            sync_frequency_interval: Sync frequency interval

        Returns:
            SourceResponse object containing the fetched data and metadata
        """
        logger.info(
            "Starting LinkedIn Ads data import",
            account_id=self.account_id,
            resource_name=resource_name,
            team_id=self.team_id,
        )

        try:
            # Get authenticated client
            client = self._get_authenticated_client()

            # Fetch data based on resource type
            data = self._fetch_resource_data(
                client,
                resource_name,
                should_use_incremental_field,
                incremental_field,
                incremental_field_type,
                db_incremental_field_last_value,
                date_start,
                date_end,
                sync_frequency_interval,
            )

            logger.info("Successfully fetched LinkedIn data", resource_name=resource_name, record_count=len(data))

            # Record success for circuit breaker
            record_success(self.account_id)

            # Process and format response
            return self._create_source_response(resource_name, data)

        except Exception as e:
            # Record failure for circuit breaker
            record_failure(self.account_id)

            logger.exception(
                "Failed to fetch LinkedIn data",
                resource_name=resource_name,
                error=str(e),
                failure_count=_failure_counts[self.account_id],
            )
            raise

    def _validate_configuration(self) -> None:
        """Validate the service configuration.

        Raises:
            ValueError: If configuration is invalid
        """
        if not self.account_id:
            raise ValueError("LinkedIn account ID is required")

        if not validate_account_id(self.account_id):
            raise ValueError(
                f"Invalid LinkedIn account ID format: '{self.account_id}'. Should be numeric, 6-15 digits."
            )

        # Check circuit breaker
        if check_circuit_breaker(self.account_id):
            failure_count = _failure_counts[self.account_id]
            raise ValueError(
                f"Circuit breaker open for account {self.account_id} due to {failure_count} consecutive failures. Please wait {CIRCUIT_BREAKER_TIMEOUT} seconds before retrying."
            )

    def _get_authenticated_client(self) -> LinkedinAdsClient:
        """Get authenticated LinkedIn Ads client.

        Returns:
            Initialized LinkedinAdsClient with access token

        Raises:
            ValueError: If integration or access token is not found
        """
        try:
            integration = Integration.objects.get(id=self.integration_id, team_id=self.team_id)
        except Integration.DoesNotExist:
            raise ValueError(
                f"LinkedIn Ads integration with ID {self.integration_id} not found for team {self.team_id}. Please re-authenticate."
            )

        access_token = integration.access_token
        if not access_token:
            raise ValueError("LinkedIn access token is required. Please re-authenticate your LinkedIn Ads integration.")

        return LinkedinAdsClient(access_token)

    def _fetch_resource_data(
        self,
        client: LinkedinAdsClient,
        resource_name: str,
        should_use_incremental_field: bool,
        incremental_field: Optional[str],
        incremental_field_type: Optional[IncrementalFieldType],
        db_incremental_field_last_value: IncrementalValue,
        date_start: Optional[str],
        date_end: Optional[str],
        sync_frequency_interval: Optional[dt.timedelta],
    ) -> list[dict[str, Any]]:
        """Fetch data for a specific resource using the client.

        Args:
            client: Authenticated LinkedIn Ads client
            resource_name: Name of the resource to fetch
            should_use_incremental_field: Whether to use incremental sync
            incremental_field: Field name for incremental sync
            incremental_field_type: Field type for incremental sync
            db_incremental_field_last_value: Last value for incremental sync
            date_start: Start date for analytics data
            date_end: End date for analytics data
            sync_frequency_interval: Sync frequency interval

        Returns:
            List of data objects from the API
        """
        # Map resource names to client methods
        resource_map = self._get_resource_method_map(client)

        if resource_name not in resource_map:
            raise ValueError(f"Unknown resource: {resource_name}")

        method, pivot = resource_map[resource_name]

        if pivot:
            # Analytics methods need pivot and dates
            analytics_date_start, analytics_date_end = self._prepare_analytics_dates(
                should_use_incremental_field,
                incremental_field,
                incremental_field_type,
                db_incremental_field_last_value,
                date_start,
                date_end,
                sync_frequency_interval,
            )
            return method(self.account_id, pivot, analytics_date_start, analytics_date_end)
        else:
            # Non-analytics methods
            if method == client.get_accounts:
                return method()
            else:
                return method(self.account_id)

    def _get_resource_method_map(self, client: LinkedinAdsClient) -> dict[str, ResourceMethodTuple]:
        """Get mapping of resource names to client methods.

        Args:
            client: LinkedIn Ads client instance

        Returns:
            Dictionary mapping resource names to (method, pivot) tuples
        """
        return {
            LinkedinAdsResource.CampaignStats: (client.get_analytics, "CAMPAIGN"),
            LinkedinAdsResource.CampaignGroupStats: (client.get_analytics, "CAMPAIGN_GROUP"),
            LinkedinAdsResource.Campaigns: (client.get_campaigns, None),
            LinkedinAdsResource.CampaignGroups: (client.get_campaign_groups, None),
            LinkedinAdsResource.Accounts: (client.get_accounts, None),
        }

    def _prepare_analytics_dates(
        self,
        should_use_incremental_field: bool,
        incremental_field: Optional[str],
        incremental_field_type: Optional[IncrementalFieldType],
        db_incremental_field_last_value: Any,
        date_start: Optional[str],
        date_end: Optional[str],
        sync_frequency_interval: Optional[dt.timedelta],
    ) -> tuple[Optional[str], Optional[str]]:
        """Prepare date range for analytics requests.

        Args:
            should_use_incremental_field: Whether to use incremental sync
            incremental_field: Field name for incremental sync
            incremental_field_type: Field type for incremental sync
            db_incremental_field_last_value: Last value for incremental sync
            date_start: Start date for analytics data
            date_end: End date for analytics data
            sync_frequency_interval: Sync frequency interval

        Returns:
            Tuple of (date_start, date_end) strings
        """
        if should_use_incremental_field and incremental_field and incremental_field_type:
            if incremental_field_type is None:
                raise ValueError("incremental_field_type can't be None when should_use_incremental_field is True")

            # Determine last value using incremental_field_type
            if db_incremental_field_last_value is None:
                last_value = (dt.datetime.now() - dt.timedelta(days=30)).strftime("%Y-%m-%d")
            else:
                last_value = db_incremental_field_last_value

            # For analytics (date-based), use incremental value as start date
            if (
                incremental_field_type == IncrementalFieldType.Date
                and incremental_field == "dateRange.start"
                and not date_start
            ):
                date_start = self.date_handler.calculate_incremental_date_range(last_value, sync_frequency_interval)

        return date_start, date_end

    def _create_source_response(self, resource_name: str, data: list[dict[str, Any]]) -> SourceResponse:
        """Create SourceResponse object from fetched data.

        Args:
            resource_name: Name of the resource
            data: Raw data from the API

        Returns:
            SourceResponse object for the pipeline
        """
        # Flatten the data structure
        flattened_data = [flatten_data_item(item, resource_name) for item in data]

        # Determine primary keys based on resource type
        primary_keys = determine_primary_keys(resource_name, flattened_data)

        return SourceResponse(
            name=resource_name,
            items=flattened_data,
            primary_keys=primary_keys,
            column_hints=None,
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="month",
            partition_keys=["date_range_start"] if flattened_data and "date_range_start" in flattened_data[0] else None,
            sort_mode="desc",
        )
