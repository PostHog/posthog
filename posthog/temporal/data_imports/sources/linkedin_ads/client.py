import json
from collections.abc import Generator
from typing import Any, Optional

import requests
from linkedin_api.clients.restli.client import RestliClient
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from .schemas import (
    LINKEDIN_ADS_ENDPOINTS,
    LINKEDIN_ADS_PIVOTS,
    RESOURCE_SCHEMAS,
    LinkedinAdsPivot,
    LinkedinAdsResource,
)

LINKEDIN_SPONSORED_URN_PREFIX = "urn:li:sponsored"
MAX_PAGE_SIZE = 1000
API_VERSION = "202508"


class LinkedinAdsRetryableError(Exception):
    """Transient LinkedIn API error (5xx / 429) that should be retried."""


class LinkedinAdsClient:
    """LinkedIn Marketing API client."""

    def __init__(self, access_token: str):
        if not access_token:
            raise ValueError("Access token required")
        self.access_token = access_token
        self.client = RestliClient()
        self.api_version = API_VERSION

    def get_accounts(self) -> list[dict[str, Any]]:
        """Get ad accounts."""
        return self._make_request(endpoint=LinkedinAdsResource.Accounts, finder="search")

    def get_campaigns(
        self, account_id: str, starting_page_token: Optional[str] = None
    ) -> Generator[tuple[list[dict[str, Any]], Optional[str]], None, None]:
        """Get campaigns with pagination, yielding each page with its nextPageToken."""
        account_endpoint = LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.Accounts]
        campaigns_endpoint = LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.Campaigns]
        yield from self._make_paginated_request(
            endpoint=LinkedinAdsResource.Campaigns,
            path=f"/{account_endpoint}/{account_id}/{campaigns_endpoint}",
            starting_page_token=starting_page_token,
        )

    def get_campaign_groups(
        self, account_id: str, starting_page_token: Optional[str] = None
    ) -> Generator[tuple[list[dict[str, Any]], Optional[str]], None, None]:
        """Get campaign groups with pagination, yielding each page with its nextPageToken."""
        account_endpoint = LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.Accounts]
        groups_endpoint = LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.CampaignGroups]
        yield from self._make_paginated_request(
            endpoint=LinkedinAdsResource.CampaignGroups,
            path=f"/{account_endpoint}/{account_id}/{groups_endpoint}",
            starting_page_token=starting_page_token,
        )

    def get_analytics(
        self,
        account_id: str,
        pivot: LinkedinAdsPivot = LinkedinAdsPivot.CAMPAIGN,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        resource = (
            LinkedinAdsResource.CampaignStats
            if pivot == LinkedinAdsPivot.CAMPAIGN
            else LinkedinAdsResource.CampaignGroupStats
        )
        fields = ",".join(self._get_fields_for_resource(resource))

        params: dict[str, Any] = {
            "q": "analytics",
            "pivot": pivot.value,
            "timeGranularity": "DAILY",
            "accounts": [f"{LINKEDIN_SPONSORED_URN_PREFIX}Account:{account_id}"],
            "fields": fields,
        }

        if date_start and date_end:
            params["dateRange"] = self._format_date_range(date_start, date_end)

        return self._make_request(endpoint=resource, finder="analytics", extra_params=params)

    def get_data_by_resource(
        self,
        resource: LinkedinAdsResource,
        account_id: str,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        starting_page_token: Optional[str] = None,
    ) -> Generator[tuple[list[dict[str, Any]], Optional[str]], None, None]:
        """Get data by resource, yielding each page and its nextPageToken (if any).

        starting_page_token applies only to paginated endpoints (campaigns, campaign_groups)
        and is ignored for single-shot endpoints (accounts, analytics).
        """
        if resource == LinkedinAdsResource.Accounts:
            yield self.get_accounts(), None
        elif resource == LinkedinAdsResource.Campaigns:
            yield from self.get_campaigns(account_id, starting_page_token=starting_page_token)
        elif resource == LinkedinAdsResource.CampaignGroups:
            yield from self.get_campaign_groups(account_id, starting_page_token=starting_page_token)
        elif resource in LINKEDIN_ADS_PIVOTS:
            yield self.get_analytics(account_id, LINKEDIN_ADS_PIVOTS[resource], date_start, date_end), None
        else:
            raise ValueError(f"Unsupported resource: {resource}")

    def _get_fields_for_resource(self, resource: LinkedinAdsResource) -> list[str]:
        """Get field names for a resource from the schema definition."""
        if resource not in RESOURCE_SCHEMAS:
            raise ValueError(f"No schema defined for resource: {resource}")
        return RESOURCE_SCHEMAS[resource]["field_names"]

    @retry(
        retry=retry_if_exception_type((LinkedinAdsRetryableError, requests.ConnectionError, requests.Timeout)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def _call_finder(self, resource_path: str, finder: str, params: dict[str, Any]) -> Any:
        """Call the Restli finder with bounded retries on transient transport and 5xx/429 errors.

        LinkedIn's edge occasionally drops TLS connections mid-handshake (SSLEOFError) or
        returns 504s; those surface here as `requests.ConnectionError` / `requests.Timeout`
        from the underlying requests.Session, or as a non-2xx response we convert to
        `LinkedinAdsRetryableError`. Non-retryable 4xx responses still raise immediately.
        """
        response = self.client.finder(
            resource_path=resource_path,
            finder_name=finder,
            access_token=self.access_token,
            query_params=params,
            version_string=self.api_version,
        )

        if response.status_code == 429 or response.status_code >= 500:
            raise LinkedinAdsRetryableError(
                f"LinkedIn API error (retryable, {response.status_code}): {response.response.text}"
            )
        if response.status_code != 200:
            raise Exception(f"LinkedIn API error ({response.status_code}): {response.response.text}")

        return response

    def _make_request(
        self, endpoint: LinkedinAdsResource, finder: str, extra_params: dict | None = None, path: str | None = None
    ) -> list[dict[str, Any]]:
        fields = self._get_fields_for_resource(endpoint)
        params = {"fields": ",".join(fields)}
        if extra_params:
            params.update(extra_params)

        resource_path = path or f"/{LINKEDIN_ADS_ENDPOINTS[endpoint]}"

        response = self._call_finder(resource_path=resource_path, finder=finder, params=params)

        return response.elements

    def _make_paginated_request(
        self,
        endpoint: LinkedinAdsResource,
        path: str,
        starting_page_token: Optional[str] = None,
    ) -> Generator[tuple[list[dict[str, Any]], Optional[str]], None, None]:
        """Make paginated requests yielding each page with its nextPageToken.

        Yields (elements, next_page_token) where next_page_token is the token to request
        the page AFTER the one just yielded (None for the final page). Callers can persist
        this token to resume a run at the next page without re-fetching yielded data.
        """
        page_token = starting_page_token

        while True:
            fields = self._get_fields_for_resource(endpoint)
            params = {"fields": ",".join(fields), "pageSize": MAX_PAGE_SIZE}
            if page_token:
                params["pageToken"] = page_token

            response = self._call_finder(resource_path=path, finder="search", params=params)

            if not response.elements:
                break

            # A malformed/empty envelope is treated as "no more pages" rather than crashing the sync.
            try:
                metadata = json.loads(response.response.text).get("metadata", {})
            except (TypeError, ValueError):
                metadata = {}
            next_page_token = metadata.get("nextPageToken")

            yield response.elements, next_page_token

            if not next_page_token:
                break

            page_token = next_page_token

    def _format_date_range(self, date_start: str, date_end: str) -> dict:
        """Format date range for LinkedIn API as structured object."""

        def format_date(date_str):
            year = int(date_str[:4])
            month = int(date_str[5:7])
            day = int(date_str[8:10])
            return {"year": year, "month": month, "day": day}

        return {"start": format_date(date_start), "end": format_date(date_end)}
