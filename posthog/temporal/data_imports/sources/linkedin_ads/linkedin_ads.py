import datetime as dt
from typing import Any, Optional

import structlog

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.warehouse.types import IncrementalFieldType
from posthog.temporal.data_imports.sources.linkedin_ads.schemas import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LINKEDIN_ADS_ENDPOINTS,
    LINKEDIN_ADS_FIELDS,
    LinkedinAdsResource,
)

logger = structlog.get_logger(__name__)

class LinkedinAdsClient:
    """Client for interacting with LinkedIn Marketing API (latest versioned).

    This client handles authentication and API requests to LinkedIn's Marketing API
    using the new /rest endpoints with proper versioning headers.
    """

    BASE_URL = "https://api.linkedin.com/rest"
    API_VERSION = "202508"  # August 2025 - latest version
    REQUEST_TIMEOUT = 30

    def __init__(self, access_token: str):
        """Initialize the LinkedIn Ads client.

        Args:
            access_token: OAuth access token for LinkedIn Marketing API
        """
        self.access_token = access_token

        # Set up session headers with latest API requirements
        self.session = type('Session', (), {
            'headers': {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "LinkedIn-Version": self.API_VERSION,
                "X-Restli-Protocol-Version": "2.0.0"
            }
        })()

        logger.info("LinkedIn Ads Client initialized",
                   base_url=self.BASE_URL,
                   api_version=self.API_VERSION)

    def _make_request(self, endpoint: str, params: dict | None = None) -> dict:
        """Make a request to LinkedIn Marketing API.

        Args:
            endpoint: API endpoint path (e.g., 'adAccounts', 'adAnalytics')
            params: Query parameters for the request

        Returns:
            JSON response from the API

        Raises:
            requests.exceptions.HTTPError: If the API returns an error status
            requests.exceptions.RequestException: If the request fails
        """
        import requests

        # Construct URL
        url = f"{self.BASE_URL}/{endpoint}"
        if params:
            # Build query string manually to avoid encoding issues
            query_parts = []
            for key, value in params.items():
                query_parts.append(f"{key}={value}")
            query_string = "&".join(query_parts)
            url = f"{url}?{query_string}"

        headers = dict(self.session.headers)

        logger.debug("Making LinkedIn API request", endpoint=endpoint)

        try:
            response = requests.get(url, headers=headers, timeout=self.REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            logger.exception("LinkedIn API request failed", error=str(e), endpoint=endpoint)
            raise

        if response.status_code >= 400:
            logger.error("LinkedIn API error",
                        endpoint=endpoint,
                        status_code=response.status_code,
                        response_text=response.text[:500])  # Limit log size

        response.raise_for_status()
        return response.json()

    def get_accounts(self) -> list[dict]:
        """Get ad accounts accessible to the authenticated user.

        Returns:
            List of ad account objects
        """
        params = {
            "q": "search",
            "fields": ",".join(LINKEDIN_ADS_FIELDS[LinkedinAdsResource.Accounts])
        }
        data = self._make_request(LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.Accounts], params)
        return data.get("elements", [])

    def get_campaigns(self, account_id: str, **kwargs) -> list[dict]:
        """Get campaigns for a specific ad account.

        Args:
            account_id: LinkedIn ad account ID
            **kwargs: Additional parameters (incremental sync not supported by LinkedIn API)

        Returns:
            List of campaign objects
        """
        endpoint = f"adAccounts/{account_id}/adCampaigns"

        params = {
            "q": "search",
            "fields": ",".join(LINKEDIN_ADS_FIELDS[LinkedinAdsResource.Campaigns])
        }

        data = self._make_request(endpoint, params)
        return data.get("elements", [])

    def get_campaign_groups(self, account_id: str, **kwargs) -> list[dict]:
        """Get campaign groups for a specific ad account.

        Args:
            account_id: LinkedIn ad account ID
            **kwargs: Additional parameters (incremental sync not supported by LinkedIn API)

        Returns:
            List of campaign group objects
        """
        endpoint = f"adAccounts/{account_id}/adCampaignGroups"

        params = {
            "q": "search",
            "fields": ",".join(LINKEDIN_ADS_FIELDS[LinkedinAdsResource.CampaignGroups])
        }

        data = self._make_request(endpoint, params)
        return data.get("elements", [])



    def get_analytics(self, account_id: str, pivot: str, date_start: str | None = None, date_end: str | None = None, **kwargs) -> list[dict]:
        """Get analytics data using the latest /rest/adAnalytics endpoint.

        Args:
            account_id: LinkedIn ad account ID
            pivot: Analytics pivot (e.g., 'CAMPAIGN', 'CREATIVE', 'ACCOUNT')
            date_start: Start date in YYYY-MM-DD format (optional)
            date_end: End date in YYYY-MM-DD format (optional)
            **kwargs: Additional parameters (unused)

        Returns:
            List of analytics data objects
        """
        # Use provided dates or default to working date range
        if date_start and date_end:
            try:
                start_date = dt.datetime.strptime(date_start, "%Y-%m-%d")
                end_date = dt.datetime.strptime(date_end, "%Y-%m-%d")

                if start_date >= end_date:
                    logger.warning("Start date >= end date, adjusting to valid range",
                                  start_date=start_date, end_date=end_date)
                    start_date = dt.datetime(2025, 7, 26)
                    end_date = dt.datetime(2025, 8, 25)

            except ValueError:
                start_date = dt.datetime(2025, 7, 26)
                end_date = dt.datetime(2025, 8, 25)
        else:
            end_date = dt.datetime.now() - dt.timedelta(days=1)
            start_date = end_date - dt.timedelta(days=30)

        params = {
            "q": "analytics",
            "pivot": pivot,
            "timeGranularity": "DAILY",
            "dateRange": f"(start:(year:{start_date.year},month:{start_date.month},day:{start_date.day}),end:(year:{end_date.year},month:{end_date.month},day:{end_date.day}))",
            "accounts": f"List(urn%3Ali%3AsponsoredAccount%3A{account_id})",
            "fields": ",".join(LINKEDIN_ADS_FIELDS[LinkedinAdsResource.CampaignStats])
        }

        logger.debug("LinkedIn Analytics request", account_id=account_id, pivot=pivot)

        data = self._make_request(LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.CampaignStats], params)
        return data.get("elements", [])


def get_incremental_fields() -> dict[str, list[tuple[str, IncrementalFieldType]]]:
    """Get incremental fields for LinkedIn Ads resources.

    Returns:
        Dictionary mapping endpoint names to lists of (field_name, field_type) tuples
    """
    from posthog.warehouse.types import IncrementalFieldType
    
    return {
        endpoint: [(field["field"], field["field_type"]) for field in fields]
        for endpoint, fields in INCREMENTAL_FIELDS.items()
    }


def get_schemas(config: Any, team_id: int) -> dict[str, Any]:
    """Get available schemas/endpoints for LinkedIn Ads.

    Args:
        config: Configuration object (unused)
        team_id: Team ID (unused)

    Returns:
        Dictionary mapping endpoint names to empty schema objects
    """
    return {endpoint: {} for endpoint in ENDPOINTS}


def linkedin_ads_source(
    config: Any,
    resource_name: str,
    team_id: int,
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
    db_incremental_field_last_value: Any = None,
    last_modified_since: Optional[dt.datetime] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> SourceResponse:
    """Main function to fetch LinkedIn Ads data.

    This function handles authentication, data fetching, and data transformation
    for LinkedIn Ads data sources. It returns a SourceResponse object that
    is compatible with the PostHog data import pipeline.

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

    Returns:
        SourceResponse object containing the fetched data and metadata

    Raises:
        ValueError: If required configuration is missing
        Exception: If data fetching fails
    """
    logger = structlog.get_logger(__name__)

    # Extract configuration
    account_id = config.account_id
    linkedin_ads_integration_id = config.linkedin_ads_integration_id

    # Get the OAuth integration to get the access token
    from posthog.models.integration import Integration
    integration = Integration.objects.get(id=linkedin_ads_integration_id, team_id=team_id)
    access_token = integration.access_token

    if not access_token:
        raise ValueError("LinkedIn access token is required")

    if not account_id:
        raise ValueError("LinkedIn account ID is required")

    logger.info("Starting LinkedIn Ads data import",
               account_id=account_id,
               resource_name=resource_name,
               team_id=team_id)

    # Initialize client
    client = LinkedinAdsClient(access_token)

    # Map resource names to methods (using schema resource names)
    resource_map = {
        LinkedinAdsResource.CampaignStats: (client.get_analytics, "CAMPAIGN"),
        LinkedinAdsResource.CampaignGroupStats: (client.get_analytics, "CAMPAIGN_GROUP"),
        LinkedinAdsResource.Campaigns: (client.get_campaigns, None),
        LinkedinAdsResource.CampaignGroups: (client.get_campaign_groups, None),
        LinkedinAdsResource.Accounts: (client.get_accounts, None)
    }

    if resource_name not in resource_map:
        raise ValueError(f"Unknown resource: {resource_name}")

    method, pivot = resource_map[resource_name]

    try:
        if pivot:
            # Analytics methods need pivot and dates
            # Handle incremental sync for analytics data
            if should_use_incremental_field and incremental_field and incremental_field_type:
                if incremental_field_type is None:
                    raise ValueError("incremental_field_type can't be None when should_use_incremental_field is True")
                
                # Determine last value using incremental_field_type
                if db_incremental_field_last_value is None:
                    last_value = incremental_type_to_initial_value(incremental_field_type)
                else:
                    last_value = db_incremental_field_last_value
                
                # For analytics (date-based), use incremental value as start date
                if incremental_field_type == IncrementalFieldType.Date and incremental_field == "dateRange.start" and not date_start:
                    if hasattr(last_value, 'strftime'):
                        date_start = last_value.strftime("%Y-%m-%d")
                    else:
                        date_start = str(last_value)
                    logger.info("Using incremental date for analytics",
                               incremental_field=incremental_field,
                               incremental_field_type=incremental_field_type,
                               date_start=date_start)
            data = method(account_id, pivot, date_start, date_end)
        else:
            # Non-analytics methods
            kwargs = {}
            
            # Handle incremental sync
            if should_use_incremental_field and incremental_field and incremental_field_type:
                if incremental_field_type is None:
                    raise ValueError("incremental_field_type can't be None when should_use_incremental_field is True")
                
                # Determine last value using incremental_field_type
                if db_incremental_field_last_value is None:
                    last_value = incremental_type_to_initial_value(incremental_field_type)
                else:
                    last_value = db_incremental_field_last_value
                
                # For non-analytics (datetime-based), use incremental value as last_modified_since
                if incremental_field_type in [IncrementalFieldType.DateTime, IncrementalFieldType.Timestamp] and incremental_field == "changeAuditStamps.lastModified.time":
                    kwargs["last_modified_since"] = last_value
                    logger.info("Using incremental sync", 
                               incremental_field=incremental_field,
                               incremental_field_type=incremental_field_type,
                               last_value=last_value)
            elif last_modified_since:
                # Fallback to explicit last_modified_since parameter
                kwargs["last_modified_since"] = last_modified_since

            # Special handling for get_accounts which doesn't take account_id
            if method == client.get_accounts:
                data = method(**kwargs)
            else:
                data = method(account_id, **kwargs)

        logger.info("Successfully fetched LinkedIn data",
                    resource_name=resource_name,
                    record_count=len(data))

        # Flatten the data structure to make it compatible with the pipeline
        flattened_data = []
        for item in data:
            flattened_item = item.copy()
            
            # Flatten dateRange structure for analytics data
            if "dateRange" in item:
                if "start" in item["dateRange"]:
                    start = item["dateRange"]["start"]
                    flattened_item["date_range_start"] = f"{start['year']}-{start['month']:02d}-{start['day']:02d}"
                if "end" in item["dateRange"]:
                    end = item["dateRange"]["end"]
                    flattened_item["date_range_end"] = f"{end['year']}-{end['month']:02d}-{end['day']:02d}"
            
            # Flatten changeAuditStamps structure for campaigns/campaign groups
            if "changeAuditStamps" in item:
                if "lastModified" in item["changeAuditStamps"] and "time" in item["changeAuditStamps"]["lastModified"]:
                    flattened_item["last_modified_time"] = item["changeAuditStamps"]["lastModified"]["time"]
                if "created" in item["changeAuditStamps"] and "time" in item["changeAuditStamps"]["created"]:
                    flattened_item["created_time"] = item["changeAuditStamps"]["created"]["time"]
            
            flattened_data.append(flattened_item)

        # Determine primary keys based on resource type
        if flattened_data:
            logger.info("Available fields in response", 
                       resource_name=resource_name,
                       fields=list(flattened_data[0].keys()) if flattened_data else [])
        
        if resource_name in [LinkedinAdsResource.CampaignStats, LinkedinAdsResource.CampaignGroupStats]:
            # Analytics data doesn't have traditional IDs, use combination of fields
            if flattened_data:
                # Check for available fields to use as primary keys
                if "pivotValues" in flattened_data[0] and "date_range_start" in flattened_data[0]:
                    primary_keys = ["pivotValues", "date_range_start"]
                elif "date_range_start" in flattened_data[0]:
                    primary_keys = ["date_range_start"]
                else:
                    # Fallback to any available field that could serve as a unique identifier
                    available_fields = list(flattened_data[0].keys())
                    primary_keys = [available_fields[0]] if available_fields else None
                    logger.warning("Using fallback primary key for analytics data",
                                 resource_name=resource_name,
                                 primary_keys=primary_keys,
                                 available_fields=available_fields)
            else:
                primary_keys = None
        else:
            # Non-analytics data has IDs
            if flattened_data:
                if "id" in flattened_data[0]:
                    primary_keys = ["id"]
                else:
                    # Fallback to any available field that could serve as a unique identifier
                    available_fields = list(flattened_data[0].keys())
                    primary_keys = [available_fields[0]] if available_fields else None
                    logger.warning("Using fallback primary key for non-analytics data",
                                 resource_name=resource_name,
                                 primary_keys=primary_keys,
                                 available_fields=available_fields)
            else:
                primary_keys = None
        
        logger.info("Primary keys determined", 
                   resource_name=resource_name,
                   primary_keys=primary_keys)

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
            sort_mode="asc"
        )

    except Exception as e:
        logger.exception("Failed to fetch LinkedIn data",
                    resource_name=resource_name,
                    error=str(e))
        raise


