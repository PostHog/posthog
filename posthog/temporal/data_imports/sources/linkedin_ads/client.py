import json
import logging
import datetime as dt
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

logger = logging.getLogger(__name__)

LINKEDIN_SPONSORED_URN_PREFIX = "urn:li:sponsored"
MAX_PAGE_SIZE = 1000
# Smaller page size for the creatives endpoint — see `get_creatives` for the rationale.
CREATIVES_PAGE_SIZE = 100
API_VERSION = "202508"
# LinkedIn's adAnalytics endpoint silently truncates responses at 15,000 records
# when using `q=analytics` (offset pagination beyond that returns errors). Larger
# queries must be sliced into smaller date ranges and concatenated.
ANALYTICS_RESPONSE_CAP = 15000
# Default chunk for historical analytics fetches. 7 days is a balance between API
# call volume (~52/year) and headroom under the cap: 7 days × ~2,100 creatives ≈
# 15k, so weekly chunks stay safe for most accounts. We log a warning when a chunk
# returns >= ANALYTICS_RESPONSE_CAP rows to surface accounts that need finer slicing.
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
        """Get creatives (the LinkedIn equivalent of "ad") with pagination.

        LinkedIn's `creatives` endpoint requires the `q=criteria` finder rather than
        the default `q=search` used by campaigns / campaign_groups (the criteria
        finder doesn't accept `searchCriteria` — that returns
        QUERY_PARAM_NOT_ALLOWED — and works fine without any criteria when the
        account is already in the URL path). The Marketing API scopes creatives by
        account via the URL path, like the other paginated resources.

        Page size is intentionally smaller than other endpoints (100 vs 1000) — the
        `partnerApiAdAccountsCreativesExternalV20250801` backend has been observed
        to return transient 500s on heavier requests, so smaller pages reduce
        single-call cost and let the retry logic recover quicker.
        """
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
        """Fetch analytics, sliced into weekly chunks to stay under LinkedIn's 15k-row
        response cap.

        LinkedIn's `q=analytics` finder silently truncates responses to
        ANALYTICS_RESPONSE_CAP records. Offset pagination (`start` / `count`) doesn't
        rescue you past the cap — the API just rejects offsets beyond it. The only
        viable workaround is to slice the date range and concatenate. We default to
        weekly chunks (see ANALYTICS_CHUNK_DAYS); if a chunk still hits the cap (very
        high-creative accounts), we log a warning so we can revisit chunk size.

        Yields `(elements, None)` tuples to match the pagination protocol used by
        the paginated entity finders (campaigns, campaign_groups, creatives) — the
        chunking IS the pagination, there's no cursor to persist. The second element
        stays None so callers can iterate uniformly via the resumable framework.

        Falls back to a single un-chunked call when no date range is supplied (the
        analytics endpoint requires one in practice, but we preserve the legacy code
        path for safety).
        """
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

        start_date = dt.date.fromisoformat(date_start)
        end_date = dt.date.fromisoformat(date_end)

        chunk_start = start_date
        while chunk_start <= end_date:
            chunk_end = min(chunk_start + dt.timedelta(days=ANALYTICS_CHUNK_DAYS - 1), end_date)
            elements = self._make_request(
                endpoint=resource,
                finder="analytics",
                extra_params=_build_params(chunk_start.isoformat(), chunk_end.isoformat()),
            )
            if len(elements) >= ANALYTICS_RESPONSE_CAP:
                # Chunk hit the cap → some rows in this window were dropped. Surface
                # this so we can shrink ANALYTICS_CHUNK_DAYS or move to adaptive
                # bisection. We don't crash because partial data is still useful.
                logger.warning(
                    "linkedin_ads.analytics_chunk_capped",
                    extra={
                        "pivot": pivot.value,
                        "chunk_start": chunk_start.isoformat(),
                        "chunk_end": chunk_end.isoformat(),
                        "cap": ANALYTICS_RESPONSE_CAP,
                        "received": len(elements),
                    },
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

        starting_page_token applies only to paginated endpoints (campaigns, campaign_groups)
        and is ignored for single-shot endpoints (accounts, analytics).
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
        """Make paginated requests yielding each page with its nextPageToken.

        Yields (elements, next_page_token) where next_page_token is the token to request
        the page AFTER the one just yielded (None for the final page). Callers can persist
        this token to resume a run at the next page without re-fetching yielded data.

        `finder` defaults to "search" (the Restli convention used by campaigns and
        campaign_groups); creatives use "criteria" since `q=search` isn't supported
        on that endpoint. `extra_params` lets callers inject finder-specific params
        (e.g. `searchCriteria` for the criteria finder); they're merged on top of the
        per-iteration params (so `pageToken` always overrides for resume correctness).
        `page_size` can be reduced when a backend handles smaller pages more reliably.
        """
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
