"""Transport layer for the Zendesk Sell (Base CRM) Core API.

Zendesk Sell's Core API lives at https://api.getbase.com/v2/. It returns a uniform envelope
(`{"items": [{"data": {...}, "meta": {...}}], "meta": {"links": {"next_page": ...}}}`) and paginates
with a 1-based `page` parameter plus `per_page` (max 100). We follow `meta.links.next_page` verbatim
rather than constructing page URLs ourselves, as the API docs instruct.

Every endpoint is full refresh. The Core API supports `sort_by` ordering but exposes no server-side
`updated_after` / `since` timestamp filter on its list endpoints, so there is no way to fetch only
changed rows cheaply — an "incremental" sort-and-skip would still page through the entire history each
run. True change capture is only available via the separate, queue-based Sync API. We therefore ship
full refresh and leave incremental off until that can be verified against a live account.
"""

import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.zendesk_sell.settings import ZENDESK_SELL_ENDPOINTS

ZENDESK_SELL_BASE_URL = "https://api.getbase.com"
PER_PAGE = 100
REQUEST_TIMEOUT_SECONDS = 60


class ZendeskSellRetryableError(Exception):
    pass


@dataclasses.dataclass
class ZendeskSellResumeConfig:
    # Full next-page URL returned by the API. None means "start the endpoint at its first page".
    next_url: str | None = None


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _build_initial_url(path: str) -> str:
    return f"{ZENDESK_SELL_BASE_URL}{path}?{urlencode({'per_page': PER_PAGE})}"


@retry(
    retry=retry_if_exception_type((ZendeskSellRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # 429 (rate limit: 10 req/s, 36k/hour) and transient 5xx are safe to retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise ZendeskSellRetryableError(f"Zendesk Sell API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Zendesk Sell API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _extract_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Unwrap each item's `data` object from the collection envelope."""
    records: list[dict[str, Any]] = []
    for item in payload.get("items", []):
        data = item.get("data")
        if isinstance(data, dict):
            records.append(data)
    return records


def get_rows(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZendeskSellResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = ZENDESK_SELL_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url: str | None = resume.next_url
        logger.debug(f"Zendesk Sell: resuming {endpoint} from URL: {url}")
    else:
        url = _build_initial_url(config.path)

    while url:
        payload = _fetch_page(session, url, headers, logger)

        records = _extract_records(payload)
        next_url = payload.get("meta", {}).get("links", {}).get("next_page")

        if records:
            yield records

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it; merge dedupes
        # on the primary key. Only persist when there's another page to resume to.
        if next_url:
            resumable_source_manager.save_state(ZendeskSellResumeConfig(next_url=next_url))

        url = next_url


def zendesk_sell_source(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZendeskSellResumeConfig],
) -> SourceResponse:
    config = ZENDESK_SELL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(access_token: str) -> bool:
    """Cheap probe that the access token is genuine: list a single contact."""
    url = f"{ZENDESK_SELL_BASE_URL}/v2/contacts?{urlencode({'per_page': 1})}"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(access_token), timeout=10)
        return response.status_code == 200
    except Exception:
        return False
