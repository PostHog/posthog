import time
import random
import datetime as dt
import re
from typing import Any, Optional
from collections import defaultdict

import requests
import structlog

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.linkedin_ads.schemas import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LINKEDIN_ADS_ENDPOINTS,
    LINKEDIN_ADS_FIELDS,
    LinkedinAdsResource,
)
from posthog.warehouse.types import IncrementalFieldType

logger = structlog.get_logger(__name__)

# LinkedIn URN constants
LINKEDIN_SPONSORED_URN_PREFIX = "urn:li:sponsored"

# Simple circuit breaker for tracking failures
_failure_counts = defaultdict(int)
_last_failure_time = defaultdict(float)
CIRCUIT_BREAKER_THRESHOLD = 5  # Max failures before circuit opens
CIRCUIT_BREAKER_TIMEOUT = 300  # 5 minutes in seconds


def validate_account_id(account_id: str) -> bool:
    """Validate LinkedIn account ID format.
    
    LinkedIn account IDs should be numeric strings.
    
    Args:
        account_id: Account ID to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not account_id:
        return False
    
    # Remove any whitespace
    account_id = account_id.strip()
    
    # Should be numeric and reasonable length (typically 8-12 digits)
    return account_id.isdigit() and 6 <= len(account_id) <= 15


def validate_date_format(date_str: str) -> bool:
    """Validate date string is in YYYY-MM-DD format.
    
    Args:
        date_str: Date string to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not date_str:
        return False
    
    # Check exact format with regex first
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return False
        
    try:
        dt.datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def check_circuit_breaker(account_id: str) -> bool:
    """Check if circuit breaker is open for an account.
    
    Args:
        account_id: LinkedIn account ID
        
    Returns:
        True if circuit is open (should fail fast), False if OK to proceed
    """
    current_time = time.time()
    
    # Reset failure count if timeout has passed
    if current_time - _last_failure_time[account_id] > CIRCUIT_BREAKER_TIMEOUT:
        _failure_counts[account_id] = 0
    
    return _failure_counts[account_id] >= CIRCUIT_BREAKER_THRESHOLD


def record_failure(account_id: str) -> None:
    """Record a failure for circuit breaker tracking.
    
    Args:
        account_id: LinkedIn account ID
    """
    _failure_counts[account_id] += 1
    _last_failure_time[account_id] = time.time()


def record_success(account_id: str) -> None:
    """Record a success, resetting failure count.
    
    Args:
        account_id: LinkedIn account ID
    """
    _failure_counts[account_id] = 0


def validate_pivot_value(pivot: str) -> bool:
    """Validate LinkedIn ads analytics pivot value.
    
    Args:
        pivot: Pivot value to validate
        
    Returns:
        True if valid, False otherwise
    """
    valid_pivots = ["CAMPAIGN", "CAMPAIGN_GROUP", "CREATIVE", "ACCOUNT"]
    return pivot in valid_pivots


def extract_linkedin_id_from_urn(urn: str) -> str:
    """Extract the ID from a LinkedIn URN.

    Args:
        urn: LinkedIn URN like "urn:li:sponsoredCampaign:185129613"

    Returns:
        The extracted ID like "185129613"
    """
    if not urn:
        return urn

    # Split by ':' and take the last part which is the ID
    parts = urn.split(':')
    if len(parts) >= 4 and parts[0] == 'urn' and parts[1] == 'li' and parts[2].startswith('sponsored'):
        return parts[3]

    # If not a recognized LinkedIn URN format, return as-is
    return urn


class LinkedinAdsError(Exception):
    """Base exception for LinkedIn Ads API errors."""
    pass


class LinkedinAdsAuthError(LinkedinAdsError):
    """Authentication error for LinkedIn Ads API."""
    pass


class LinkedinAdsRateLimitError(LinkedinAdsError):
    """Rate limit error for LinkedIn Ads API."""
    pass


class LinkedinAdsClient:
    """Client for interacting with LinkedIn Marketing API (latest versioned).

    This client handles authentication and API requests to LinkedIn's Marketing API
    using the new /rest endpoints with proper versioning headers.
    """

    BASE_URL = "https://api.linkedin.com/rest"
    API_VERSION = "202508"  # August 2025 - latest version
    REQUEST_TIMEOUT = 30
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # Base delay in seconds
    RATE_LIMIT_DELAY = 60  # Rate limit retry delay

    def __init__(self, access_token: str):
        """Initialize the LinkedIn Ads client.

        Args:
            access_token: OAuth access token for LinkedIn Marketing API
        """
        if not access_token:
            raise ValueError("Access token is required")

        self.access_token = access_token

        # Set up proper requests session
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "LinkedIn-Version": self.API_VERSION,
            "X-Restli-Protocol-Version": "2.0.0"
        })

        logger.info("LinkedIn Ads Client initialized",
                   base_url=self.BASE_URL,
                   api_version=self.API_VERSION)

    def _make_request(self, endpoint: str, params: dict | None = None) -> dict:
        """Make a request to LinkedIn Marketing API with retry logic.

        Args:
            endpoint: API endpoint path (e.g., 'adAccounts', 'adAnalytics')
            params: Query parameters for the request

        Returns:
            JSON response from the API

        Raises:
            LinkedinAdsAuthError: If authentication fails
            LinkedinAdsRateLimitError: If rate limit is exceeded
            LinkedinAdsError: For other API errors
            requests.exceptions.RequestException: If the request fails
        """
        # Construct URL with proper encoding
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

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = self.session.get(url, headers=headers, timeout=self.REQUEST_TIMEOUT)

                # Handle specific status codes
                if response.status_code == 401:
                    error_msg = "LinkedIn API authentication failed. Please check your access token."
                    try:
                        error_detail = response.json().get('message', '')
                        if error_detail:
                            error_msg += f" Details: {error_detail}"
                    except ValueError:
                        pass
                    logger.error("LinkedIn API auth error",
                               endpoint=endpoint,
                               status_code=response.status_code)
                    capture_exception(LinkedinAdsAuthError(error_msg))
                    raise LinkedinAdsAuthError(error_msg)

                elif response.status_code == 429:
                    # Rate limit exceeded
                    retry_after = int(response.headers.get('Retry-After', self.RATE_LIMIT_DELAY))
                    if attempt < self.MAX_RETRIES:
                        logger.warning("LinkedIn API rate limit hit, retrying",
                                     endpoint=endpoint,
                                     attempt=attempt + 1,
                                     retry_after=retry_after)
                        time.sleep(retry_after)
                        continue
                    else:
                        error_msg = f"LinkedIn API rate limit exceeded. Retry after {retry_after} seconds."
                        logger.error("LinkedIn API rate limit exceeded", endpoint=endpoint)
                        capture_exception(LinkedinAdsRateLimitError(error_msg))
                        raise LinkedinAdsRateLimitError(error_msg)

                elif response.status_code >= 500:
                    # Server error - retry with exponential backoff
                    if attempt < self.MAX_RETRIES:
                        delay = self.RETRY_DELAY * (2 ** attempt) + random.uniform(0, 1)
                        logger.warning("LinkedIn API server error, retrying",
                                     endpoint=endpoint,
                                     attempt=attempt + 1,
                                     status_code=response.status_code,
                                     delay=delay)
                        time.sleep(delay)
                        continue
                    else:
                        error_msg = f"LinkedIn API server error: {response.status_code}"
                        logger.error("LinkedIn API server error",
                                   endpoint=endpoint,
                                   status_code=response.status_code,
                                   response_text=response.text[:500])
                        capture_exception(LinkedinAdsError(error_msg))
                        raise LinkedinAdsError(error_msg)

                elif response.status_code >= 400:
                    # Client error
                    error_msg = f"LinkedIn API client error: {response.status_code}"
                    try:
                        error_detail = response.json().get('message', response.text[:200])
                        if error_detail:
                            error_msg += f" Details: {error_detail}"
                    except ValueError:
                        error_msg += f" Response: {response.text[:200]}"

                    logger.error("LinkedIn API client error",
                               endpoint=endpoint,
                               status_code=response.status_code,
                               response_text=response.text[:500])
                    capture_exception(LinkedinAdsError(error_msg))
                    raise LinkedinAdsError(error_msg)

                # Success
                try:
                    return response.json()
                except ValueError as e:
                    logger.exception("Failed to parse JSON response",
                               endpoint=endpoint,
                               status_code=response.status_code,
                               response_text=response.text[:200])
                    raise LinkedinAdsError(f"Invalid JSON response from LinkedIn API: {str(e)}")

            except requests.exceptions.Timeout:
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAY * (2 ** attempt)
                    logger.warning("LinkedIn API request timeout, retrying",
                                 endpoint=endpoint,
                                 attempt=attempt + 1,
                                 delay=delay)
                    time.sleep(delay)
                    continue
                else:
                    error_msg = "LinkedIn API request timeout"
                    logger.exception("LinkedIn API request timeout", endpoint=endpoint)
                    capture_exception(LinkedinAdsError(error_msg))
                    raise LinkedinAdsError(error_msg)

            except requests.exceptions.RequestException as e:
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAY * (2 ** attempt)
                    logger.warning("LinkedIn API request failed, retrying",
                                 endpoint=endpoint,
                                 attempt=attempt + 1,
                                 error=str(e),
                                 delay=delay)
                    time.sleep(delay)
                    continue
                else:
                    logger.exception("LinkedIn API request failed",
                                   error=str(e),
                                   endpoint=endpoint)
                    capture_exception(e)
                    raise

        # This should never be reached
        raise LinkedinAdsError("Max retries exceeded")

    def _get_paginated_data(self, endpoint: str, params: dict) -> list[dict]:
        """Get all paginated data from LinkedIn API.

        Args:
            endpoint: API endpoint path
            params: Query parameters

        Returns:
            List of all elements from all pages
        """
        all_elements = []
        page_token = None
        page_size = 100  # LinkedIn's default/recommended page size
        page_number = 1

        logger.debug("Starting pagination",
                    endpoint=endpoint,
                    page_size=page_size)

        while True:
            page_params = params.copy()
            page_params["pageSize"] = page_size

            if page_token:
                page_params["pageToken"] = page_token

            logger.debug("Fetching page",
                        endpoint=endpoint,
                        page_number=page_number)

            data = self._make_request(endpoint, page_params)

            # Validate response structure
            if not data or "elements" not in data:
                logger.error("Invalid API response structure",
                           endpoint=endpoint,
                           response_keys=list(data.keys()) if data else None)
                raise LinkedinAdsError(f"Invalid response structure from {endpoint}: missing 'elements' field")

            elements = data.get("elements", [])
            all_elements.extend(elements)

            # Check if we have more pages - LinkedIn uses metadata.nextPageToken
            metadata = data.get("metadata", {})
            page_token = metadata.get("nextPageToken")

            logger.debug("Page processed",
                        endpoint=endpoint,
                        page_number=page_number,
                        elements_count=len(elements),
                        total_so_far=len(all_elements),
                        has_next_page=bool(page_token))

            # Stop if no pageToken (LinkedIn returns null when done)
            if not page_token:
                break

            page_number += 1

            # Safety check to prevent infinite loops
            if page_number > 1000:
                logger.error("Pagination safety limit reached",
                           endpoint=endpoint,
                           page_number=page_number,
                           total_elements=len(all_elements))
                break

        logger.info("Pagination complete",
                   endpoint=endpoint,
                   total_pages=page_number,
                   total_elements=len(all_elements))
        return all_elements

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
            **kwargs: Additional parameters (unused - LinkedIn API returns all campaigns)

        Returns:
            List of campaign objects
        """
        if not account_id:
            raise ValueError("account_id is required")

        endpoint = f"adAccounts/{account_id}/adCampaigns"

        params = {
            "q": "search",
            "fields": ",".join(LINKEDIN_ADS_FIELDS[LinkedinAdsResource.Campaigns])
        }

        return self._get_paginated_data(endpoint, params)


    def get_campaign_groups(self, account_id: str, **kwargs) -> list[dict]:
        """Get campaign groups for a specific ad account.

        Args:
            account_id: LinkedIn ad account ID
            **kwargs: Additional parameters (unused - LinkedIn API returns all campaign groups)

        Returns:
            List of campaign group objects
        """
        if not account_id:
            raise ValueError("account_id is required")

        endpoint = f"adAccounts/{account_id}/adCampaignGroups"
        params = {
            "q": "search",
            "fields": ",".join(LINKEDIN_ADS_FIELDS[LinkedinAdsResource.CampaignGroups])
        }

        return self._get_paginated_data(endpoint, params)



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
        if not account_id:
            raise ValueError("account_id is required")
        if not pivot:
            raise ValueError("pivot is required")

        # Validate pivot value
        if not validate_pivot_value(pivot):
            valid_pivots = ["CAMPAIGN", "CAMPAIGN_GROUP", "CREATIVE", "ACCOUNT"]
            raise ValueError(f"Invalid pivot '{pivot}'. Must be one of: {valid_pivots}")

        # LinkedIn API has a limit on date range (typically 5 year)
        max_days = 365 * 5

        # Use provided dates or default to reasonable date range
        if date_start or date_end:
            # If only start date provided (incremental), use current date as end
            if date_start and not date_end:
                try:
                    start_date = dt.datetime.strptime(date_start, "%Y-%m-%d")
                    end_date = dt.datetime.now() - dt.timedelta(days=1)  # Yesterday
                    logger.info("Using incremental date range",
                               start_date=start_date.strftime("%Y-%m-%d"),
                               end_date=end_date.strftime("%Y-%m-%d"))
                except ValueError as e:
                    logger.warning("Invalid start date format, using default range",
                                 date_start=date_start, error=str(e))
                    end_date = dt.datetime.now() - dt.timedelta(days=1)
                    start_date = end_date - dt.timedelta(days=30)
            # If only end date provided, use 30 days before as start
            elif date_end and not date_start:
                try:
                    end_date = dt.datetime.strptime(date_end, "%Y-%m-%d")
                    start_date = end_date - dt.timedelta(days=30)
                except ValueError as e:
                    logger.warning("Invalid end date format, using default range",
                                 date_end=date_end, error=str(e))
                    end_date = dt.datetime.now() - dt.timedelta(days=1)
                    start_date = end_date - dt.timedelta(days=30)
            # Both dates provided
            else:
                try:
                    start_date = dt.datetime.strptime(date_start, "%Y-%m-%d")
                    end_date = dt.datetime.strptime(date_end, "%Y-%m-%d")

                    if start_date >= end_date:
                        logger.warning("Start date >= end date, adjusting to valid range",
                                      start_date=start_date, end_date=end_date)
                        start_date = end_date - dt.timedelta(days=30)

                except ValueError as e:
                    logger.warning("Invalid date format, using default range",
                                 date_start=date_start, date_end=date_end, error=str(e))
                    end_date = dt.datetime.now() - dt.timedelta(days=1)
                    start_date = end_date - dt.timedelta(days=30)
        else:
            # Default to last max_days
            end_date = dt.datetime.now() - dt.timedelta(days=1)
            start_date = end_date - dt.timedelta(days=max_days)

        if (end_date - start_date).days > max_days:
            logger.warning("Date range too large, limiting to 5 years",
                         original_start=start_date, original_end=end_date)
            start_date = end_date - dt.timedelta(days=max_days)

        params = {
            "q": "analytics",
            "pivot": pivot,
            "timeGranularity": "DAILY",
            "dateRange": f"(start:(year:{start_date.year},month:{start_date.month},day:{start_date.day}),end:(year:{end_date.year},month:{end_date.month},day:{end_date.day}))",
            "accounts": f"List(urn%3Ali%3AsponsoredAccount%3A{account_id})",
            "fields": ",".join(LINKEDIN_ADS_FIELDS[LinkedinAdsResource.CampaignStats])
        }

        logger.debug("LinkedIn Analytics request",
                    account_id=account_id,
                    pivot=pivot,
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"))

        data = self._make_request(LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.CampaignStats], params)
        return data.get("elements", [])


def get_incremental_fields() -> dict[str, list[tuple[str, IncrementalFieldType]]]:
    """Get incremental fields for LinkedIn Ads resources.

    Returns:
        Dictionary mapping endpoint names to lists of (field_name, field_type) tuples
    """

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
    sync_frequency_interval: Optional[dt.timedelta] = None,
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
        sync_frequency_interval: Sync frequency interval to limit incremental lookback period

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

    # Validate configuration
    if not account_id:
        raise ValueError("LinkedIn account ID is required")
    
    if not validate_account_id(account_id):
        raise ValueError(f"Invalid LinkedIn account ID format: '{account_id}'. Should be numeric, 6-15 digits.")
    
    # Check circuit breaker
    if check_circuit_breaker(account_id):
        failure_count = _failure_counts[account_id]
        raise ValueError(f"Circuit breaker open for account {account_id} due to {failure_count} consecutive failures. Please wait {CIRCUIT_BREAKER_TIMEOUT} seconds before retrying.")
    
    # Validate dates if provided
    if date_start and not validate_date_format(date_start):
        raise ValueError(f"Invalid date_start format: '{date_start}'. Expected YYYY-MM-DD format.")
    
    if date_end and not validate_date_format(date_end):
        raise ValueError(f"Invalid date_end format: '{date_end}'. Expected YYYY-MM-DD format.")

    # Get the OAuth integration to get the access token
    from posthog.models.integration import Integration
    try:
        integration = Integration.objects.get(id=linkedin_ads_integration_id, team_id=team_id)
    except Integration.DoesNotExist:
        raise ValueError(f"LinkedIn Ads integration with ID {linkedin_ads_integration_id} not found for team {team_id}. Please re-authenticate.")
    
    access_token = integration.access_token
    if not access_token:
        raise ValueError("LinkedIn access token is required. Please re-authenticate your LinkedIn Ads integration.")

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
                    # If sync frequency interval is provided, limit the lookback period
                    if sync_frequency_interval:
                        # Calculate start date based on sync frequency interval
                        now = dt.datetime.now()
                        max_lookback_days = max(1, sync_frequency_interval.total_seconds() / 86400)  # Convert to days, minimum 1 day
                        calculated_start = now - dt.timedelta(days=max_lookback_days)

                        # Use the later of: last_value or calculated_start (don't go further back than sync frequency)
                        if hasattr(last_value, 'strftime'):
                            last_value_date = last_value if isinstance(last_value, dt.datetime) else dt.datetime.combine(last_value, dt.time.min)
                        else:
                            last_value_date = dt.datetime.strptime(str(last_value), "%Y-%m-%d")

                        effective_start = max(last_value_date, calculated_start)
                        date_start = effective_start.strftime("%Y-%m-%d")

                        logger.info("Using incremental date with sync frequency limit for analytics",
                                   incremental_field=incremental_field,
                                   incremental_field_type=incremental_field_type,
                                   last_value=last_value,
                                   sync_frequency_interval=sync_frequency_interval,
                                   max_lookback_days=max_lookback_days,
                                   calculated_start=calculated_start.strftime("%Y-%m-%d"),
                                   effective_start=effective_start.strftime("%Y-%m-%d"),
                                   date_start=date_start)
                    else:
                        # No sync frequency interval, use last value as-is
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
            # Non-analytics methods (campaigns, campaign_groups, accounts)
            # These endpoints don't support API-level filtering - incremental sync handled by pipeline
            if method == client.get_accounts:
                data = method()
            else:
                data = method(account_id)

        logger.info("Successfully fetched LinkedIn data",
                    resource_name=resource_name,
                    record_count=len(data))
        
        # Record success for circuit breaker
        record_success(account_id)

        # Flatten the data structure to make it compatible with the pipeline
        flattened_data = []
        for item in data:
            flattened_item = item.copy()

            # Flatten dateRange structure for analytics data
            if "dateRange" in item:
                if "start" in item["dateRange"]:
                    start = item["dateRange"]["start"]
                    flattened_item["date_range_start"] = dt.date(start['year'], start['month'], start['day'])
                if "end" in item["dateRange"]:
                    end = item["dateRange"]["end"]
                    flattened_item["date_range_end"] = dt.date(end['year'], end['month'], end['day'])

            # Transform pivotValues from array to specific pivot columns
            if "pivotValues" in item and isinstance(item["pivotValues"], list):
                # Extract IDs and create specific columns based on pivot type
                for pivot_value in item["pivotValues"]:
                    if isinstance(pivot_value, str) and pivot_value.startswith(LINKEDIN_SPONSORED_URN_PREFIX):
                        # Remove the LinkedIn URN prefix to get the type and ID part
                        # "urn:li:sponsoredCampaign:185129613" -> "Campaign:185129613"
                        cleaned = pivot_value.replace(LINKEDIN_SPONSORED_URN_PREFIX, "")

                        if ":" in cleaned:
                            pivot_type, pivot_id_str = cleaned.split(":", 1)

                            # Convert ID to integer (LinkedIn IDs are always integers)
                            try:
                                pivot_id = int(pivot_id_str)
                            except ValueError:
                                logger.warning("Failed to convert pivot ID to int",
                                             pivot_id=pivot_id_str,
                                             pivot_type=pivot_type,
                                             resource_name=resource_name)
                                pivot_id = pivot_id_str  # Keep as string if conversion fails

                            # Convert pivot type to lowercase column name
                            if pivot_type == "Campaign":
                                flattened_item["campaign_id"] = pivot_id
                            elif pivot_type == "CampaignGroup":
                                flattened_item["campaign_group_id"] = pivot_id
                            elif pivot_type == "Creative":
                                flattened_item["creative_id"] = pivot_id
                            elif pivot_type == "Account":
                                flattened_item["account_id"] = pivot_id
                            else:
                                # For any other pivot types, use a generic pattern
                                column_name = pivot_type.lower() + "_id"
                                flattened_item[column_name] = pivot_id


            # Convert cost_in_usd from String to Float
            if "costInUsd" in item:
                try:
                    flattened_item["cost_in_usd"] = float(item["costInUsd"]) if item["costInUsd"] is not None else None
                except (ValueError, TypeError):
                    logger.warning("Failed to convert costInUsd to float",
                                 cost_in_usd=item["costInUsd"],
                                 resource_name=resource_name)
                    flattened_item["cost_in_usd"] = None
                # Remove the original camelCase field since we've converted it
                flattened_item.pop("costInUsd", None)

            # Flatten changeAuditStamps structure for campaigns/campaign groups
            if "changeAuditStamps" in item:
                if "lastModified" in item["changeAuditStamps"] and "time" in item["changeAuditStamps"]["lastModified"]:
                    flattened_item["last_modified_time"] = item["changeAuditStamps"]["lastModified"]["time"]
                if "created" in item["changeAuditStamps"] and "time" in item["changeAuditStamps"]["created"]:
                    flattened_item["created_time"] = item["changeAuditStamps"]["created"]["time"]

            flattened_data.append(flattened_item)

        # Determine primary keys based on resource type
        if resource_name in [LinkedinAdsResource.CampaignStats, LinkedinAdsResource.CampaignGroupStats]:
            # Analytics data uses combination of fields for uniqueness
            if flattened_data and "pivotValues" in flattened_data[0] and "date_range_start" in flattened_data[0]:
                primary_keys = ["pivotValues", "date_range_start"]
            elif flattened_data and "date_range_start" in flattened_data[0]:
                primary_keys = ["date_range_start"]
            else:
                primary_keys = None
                logger.warning("No suitable primary keys found for analytics data", resource_name=resource_name)
        else:
            # Entity data uses ID field
            if flattened_data and "id" in flattened_data[0]:
                primary_keys = ["id"]
            else:
                primary_keys = None
                logger.warning("No ID field found for entity data", resource_name=resource_name)

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
            sort_mode="desc"
        )

    except Exception as e:
        # Record failure for circuit breaker
        record_failure(account_id)
        
        logger.exception("Failed to fetch LinkedIn data",
                    resource_name=resource_name,
                    error=str(e),
                    failure_count=_failure_counts[account_id])
        raise


