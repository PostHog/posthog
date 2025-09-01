"""LinkedIn Ads API client with improved separation of concerns."""

from typing import Any, Optional

import requests
import structlog

from ..utils.constants import API_BASE_URL, API_VERSION, DEFAULT_PAGE_SIZE, MAX_PAGES_SAFETY_LIMIT
from ..utils.date_handler import LinkedinAdsDateHandler
from ..utils.schemas import LINKEDIN_ADS_ENDPOINTS, LINKEDIN_ADS_FIELDS, LinkedinAdsResource
from ..utils.types import (
    LinkedinAccountType,
    LinkedinAnalyticsType,
    LinkedinCampaignGroupType,
    LinkedinCampaignType,
    RequestParams,
)
from .exceptions import LinkedinAdsError
from .request_handler import LinkedinAdsRequestHandler

logger = structlog.get_logger(__name__)


class LinkedinAdsClient:
    """Client for interacting with LinkedIn Marketing API.

    This client uses composition to separate concerns:
    - Request handling with retry logic
    - Date range calculations
    - Error handling
    - Pagination logic
    """

    def __init__(self, access_token: str):
        """Initialize the LinkedIn Ads client.

        Args:
            access_token: OAuth access token for LinkedIn Marketing API

        Raises:
            ValueError: If access token is not provided
        """
        if not access_token:
            raise ValueError("Access token is required")

        self.access_token = access_token
        self.base_url = API_BASE_URL
        self.api_version = API_VERSION

        # Initialize session with authentication headers
        self.session = self._create_session()

        # Initialize composed services
        self.request_handler = LinkedinAdsRequestHandler(self.session)
        self.date_handler = LinkedinAdsDateHandler()

        logger.info("LinkedIn Ads Client initialized", base_url=self.base_url, api_version=self.api_version)

    def get_accounts(self) -> list[LinkedinAccountType]:
        """Get ad accounts accessible to the authenticated user.

        Returns:
            List of ad account objects
        """
        endpoint = LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.Accounts]
        params = {"q": "search", "fields": ",".join(LINKEDIN_ADS_FIELDS[LinkedinAdsResource.Accounts])}

        url = f"{self.base_url}/{endpoint}"
        data = self.request_handler.make_request(url, params)
        return data.get("elements", [])

    def get_campaigns(self, account_id: str, **kwargs) -> list[LinkedinCampaignType]:
        """Get campaigns for a specific ad account.

        Args:
            account_id: LinkedIn ad account ID
            **kwargs: Additional parameters (unused - interface compliance)

        Returns:
            List of campaign objects
        """
        self._validate_account_id(account_id)

        endpoint = f"adAccounts/{account_id}/adCampaigns"
        params = {"q": "search", "fields": ",".join(LINKEDIN_ADS_FIELDS[LinkedinAdsResource.Campaigns])}

        return self._get_paginated_data(endpoint, params)

    def get_campaign_groups(self, account_id: str, **kwargs) -> list[LinkedinCampaignGroupType]:
        """Get campaign groups for a specific ad account.

        Args:
            account_id: LinkedIn ad account ID
            **kwargs: Additional parameters (unused - interface compliance)

        Returns:
            List of campaign group objects
        """
        self._validate_account_id(account_id)

        endpoint = f"adAccounts/{account_id}/adCampaignGroups"
        params = {"q": "search", "fields": ",".join(LINKEDIN_ADS_FIELDS[LinkedinAdsResource.CampaignGroups])}

        return self._get_paginated_data(endpoint, params)

    def get_analytics(
        self, account_id: str, pivot: str, date_start: Optional[str] = None, date_end: Optional[str] = None, **kwargs
    ) -> list[LinkedinAnalyticsType]:
        """Get analytics data using the /rest/adAnalytics endpoint.

        Args:
            account_id: LinkedIn ad account ID
            pivot: Analytics pivot (e.g., 'CAMPAIGN', 'CREATIVE', 'ACCOUNT')
            date_start: Start date in YYYY-MM-DD format (optional)
            date_end: End date in YYYY-MM-DD format (optional)
            **kwargs: Additional parameters (unused)

        Returns:
            List of analytics data objects
        """
        self._validate_account_id(account_id)
        self._validate_pivot(pivot)

        # Calculate date range using date handler
        start_date, end_date = self.date_handler.calculate_date_range(date_start, date_end)
        date_range_param = self.date_handler.format_linkedin_date_range(start_date, end_date)

        params = {
            "q": "analytics",
            "pivot": pivot,
            "timeGranularity": "DAILY",
            "dateRange": date_range_param,
            "accounts": f"List(urn%3Ali%3AsponsoredAccount%3A{account_id})",
            "fields": ",".join(LINKEDIN_ADS_FIELDS[LinkedinAdsResource.CampaignStats]),
        }

        endpoint = LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.CampaignStats]
        url = f"{self.base_url}/{endpoint}"
        data = self.request_handler.make_request(url, params)
        return data.get("elements", [])

    def _create_session(self) -> requests.Session:
        """Create and configure requests session with authentication headers.

        Returns:
            Configured requests session
        """
        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
                "LinkedIn-Version": self.api_version,
                "X-Restli-Protocol-Version": "2.0.0",
            }
        )
        return session

    def _get_paginated_data(self, endpoint: str, params: RequestParams) -> list[dict[str, Any]]:
        """Get all paginated data from LinkedIn API.

        Args:
            endpoint: API endpoint path
            params: Query parameters

        Returns:
            List of all elements from all pages
        """
        all_elements = []
        page_token = None
        page_number = 1

        while True:
            page_params = params.copy()
            page_params["pageSize"] = DEFAULT_PAGE_SIZE

            if page_token:
                page_params["pageToken"] = page_token

            url = f"{self.base_url}/{endpoint}"
            data = self.request_handler.make_request(url, page_params)

            # Validate response structure
            if not data or "elements" not in data:
                logger.error(
                    "Invalid API response structure",
                    endpoint=endpoint,
                    response_keys=list(data.keys()) if data else None,
                )
                raise LinkedinAdsError(f"Invalid response structure from {endpoint}: missing 'elements' field")

            elements = data.get("elements", [])
            all_elements.extend(elements)

            # Check for next page
            metadata = data.get("metadata", {})
            page_token = metadata.get("nextPageToken")

            if not page_token:
                break

            page_number += 1

            # Safety check to prevent infinite loops
            if page_number > MAX_PAGES_SAFETY_LIMIT:
                logger.error(
                    "Pagination safety limit reached",
                    endpoint=endpoint,
                    page_number=page_number,
                    total_elements=len(all_elements),
                )
                break

        logger.info("Pagination complete", endpoint=endpoint, total_pages=page_number, total_elements=len(all_elements))
        return all_elements

    def _validate_account_id(self, account_id: str) -> None:
        """Validate account ID parameter.

        Args:
            account_id: LinkedIn ad account ID

        Raises:
            ValueError: If account ID is invalid
        """
        if not account_id:
            raise ValueError("account_id is required")

    def _validate_pivot(self, pivot: str) -> None:
        """Validate pivot parameter for analytics requests.

        Args:
            pivot: Analytics pivot value

        Raises:
            ValueError: If pivot is invalid
        """
        if not pivot:
            raise ValueError("pivot is required")

        valid_pivots = ["CAMPAIGN", "CAMPAIGN_GROUP", "CREATIVE", "ACCOUNT"]
        if pivot not in valid_pivots:
            raise ValueError(f"Invalid pivot '{pivot}'. Must be one of: {valid_pivots}")
