import json
import datetime as dt
from collections.abc import Generator
from typing import Any, Optional

import requests
import structlog
from linkedin_api.clients.restli.client import RestliClient
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from .schemas import (
    LINKEDIN_ADS_ENDPOINTS,
    LINKEDIN_ADS_PIVOTS,
    RESOURCE_SCHEMAS,
    LinkedinAdsPivot,
    LinkedinAdsResource,
)

logger = structlog.get_logger(__name__)

LINKEDIN_SPONSORED_URN_PREFIX = "urn:li:sponsored"
MAX_PAGE_SIZE = 1000
CREATIVES_PAGE_SIZE = 100  # creatives backend returns transient 500s on heavier requests
API_VERSION = "202508"
# `q=analytics` truncates at 15k rows; we slice the date range to stay under it.
ANALYTICS_RESPONSE_CAP = 15000
ANALYTICS_CHUNK_DAYS = 7


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

    def get_creatives(
        self, account_id: str, starting_page_token: Optional[str] = None
    ) -> Generator[tuple[list[dict[str, Any]], Optional[str]], None, None]:
        """Get creatives with pagination. Uses `q=criteria` and reduced page size
        (the creatives backend 500s on heavier requests)."""
        account_endpoint = LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.Accounts]
        creatives_endpoint = LINKEDIN_ADS_ENDPOINTS[LinkedinAdsResource.Creatives]
        yield from self._make_paginated_request(
            endpoint=LinkedinAdsResource.Creatives,
            path=f"/{account_endpoint}/{account_id}/{creatives_endpoint}",
            starting_page_token=starting_page_token,
            finder="criteria",
            page_size=CREATIVES_PAGE_SIZE,
        )

    def get_analytics(
        self,
        account_id: str,
        pivot: LinkedinAdsPivot = LinkedinAdsPivot.CAMPAIGN,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> Generator[tuple[list[dict[str, Any]], None], None, None]:
        """Fetch analytics in weekly chunks to stay under the 15k-row response
        cap. Capped chunks yield partial data and log a warning — we don't
        retry/split because extra calls under rate-limit pressure cost more
        than the missing rows recover."""
        resource_by_pivot = {
            LinkedinAdsPivot.CAMPAIGN: LinkedinAdsResource.CampaignStats,
            LinkedinAdsPivot.CAMPAIGN_GROUP: LinkedinAdsResource.CampaignGroupStats,
            LinkedinAdsPivot.CREATIVE: LinkedinAdsResource.CreativeStats,
        }
        resource = resource_by_pivot.get(pivot, LinkedinAdsResource.CampaignStats)
        fields = ",".join(self._get_fields_for_resource(resource))
        accounts = [f"{LINKEDIN_SPONSORED_URN_PREFIX}Account:{account_id}"]

        def _build_params(chunk_start: Optional[str], chunk_end: Optional[str]) -> dict[str, Any]:
            params: dict[str, Any] = {
                "q": "analytics",
                "pivot": pivot.value,
                "timeGranularity": "DAILY",
                "accounts": accounts,
                "fields": fields,
            }
            if chunk_start and chunk_end:
                params["dateRange"] = self._format_date_range(chunk_start, chunk_end)
            return params

        if not (date_start and date_end):
            yield (
                self._make_request(endpoint=resource, finder="analytics", extra_params=_build_params(None, None)),
                None,
            )
            return

        chunk_start = dt.date.fromisoformat(date_start)
        end_date = dt.date.fromisoformat(date_end)
        while chunk_start <= end_date:
            chunk_end = min(chunk_start + dt.timedelta(days=ANALYTICS_CHUNK_DAYS - 1), end_date)
            elements = self._make_request(
                endpoint=resource,
                finder="analytics",
                extra_params=_build_params(chunk_start.isoformat(), chunk_end.isoformat()),
            )
            if len(elements) >= ANALYTICS_RESPONSE_CAP:
                logger.warning(
                    "linkedin_ads.analytics_chunk_capped",
                    pivot=pivot.value,
                    chunk_start=chunk_start.isoformat(),
                    chunk_end=chunk_end.isoformat(),
                    received=len(elements),
                )
            yield elements, None
            chunk_start = chunk_end + dt.timedelta(days=1)

    def get_data_by_resource(
        self,
        resource: LinkedinAdsResource,
        account_id: str,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        starting_page_token: Optional[str] = None,
    ) -> Generator[tuple[list[dict[str, Any]], Optional[str]], None, None]:
        """Get data by resource, yielding each page and its nextPageToken (if any).

        `starting_page_token` applies to the paginated entity endpoints (campaigns,
        campaign_groups, creatives) and is ignored for single-shot endpoints
        (accounts, analytics — analytics paginates by date-range chunking instead).
        """
        if resource == LinkedinAdsResource.Accounts:
            yield self.get_accounts(), None
        elif resource == LinkedinAdsResource.Campaigns:
            yield from self.get_campaigns(account_id, starting_page_token=starting_page_token)
        elif resource == LinkedinAdsResource.CampaignGroups:
            yield from self.get_campaign_groups(account_id, starting_page_token=starting_page_token)
        elif resource == LinkedinAdsResource.Creatives:
            yield from self.get_creatives(account_id, starting_page_token=starting_page_token)
        elif resource in LINKEDIN_ADS_PIVOTS:
            yield from self.get_analytics(account_id, LINKEDIN_ADS_PIVOTS[resource], date_start, date_end)
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
        finder: str = "search",
        page_size: int = MAX_PAGE_SIZE,
        extra_params: Optional[dict[str, Any]] = None,
    ) -> Generator[tuple[list[dict[str, Any]], Optional[str]], None, None]:
        """Yield each page as `(elements, next_page_token)` (None on the last page).
        Callers persist `next_page_token` to resume without re-fetching."""
        page_token = starting_page_token

        while True:
            fields = self._get_fields_for_resource(endpoint)
            params: dict[str, Any] = {"fields": ",".join(fields), "pageSize": page_size}
            if extra_params:
                params.update(extra_params)
            if page_token:
                params["pageToken"] = page_token

            response = self._call_finder(resource_path=path, finder=finder, params=params)

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
