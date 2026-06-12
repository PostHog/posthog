from collections.abc import Iterator
from typing import Any
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.cloudflare.settings import CLOUDFLARE_ENDPOINTS
from posthog.temporal.data_imports.sources.common.http import make_tracked_session

CLOUDFLARE_BASE_URL = "https://api.cloudflare.com/client/v4"
# Cloudflare list pages cap at 50 by default; most endpoints allow more.
PAGE_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 60
# 1200 req/5min global API rate limit; 429s carry Retry-After but backoff suffices.
MAX_RETRY_ATTEMPTS = 5


class CloudflareRetryableError(Exception):
    pass


def _get_session(api_token: str) -> requests.Session:
    return make_tracked_session(headers={"Authorization": f"Bearer {api_token}"}, redact_values=(api_token,))


def validate_credentials(api_token: str) -> bool:
    """Confirm the API token is valid with Cloudflare's token verify endpoint."""
    try:
        response = _get_session(api_token).get(
            f"{CLOUDFLARE_BASE_URL}/user/tokens/verify",
            timeout=10,
        )
        return response.status_code == 200 and bool(response.json().get("success"))
    except Exception:
        return False


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = CLOUDFLARE_ENDPOINTS[endpoint]
    session = _get_session(api_token)

    @retry(
        retry=retry_if_exception_type((CloudflareRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch(path: str, page: int) -> dict[str, Any]:
        url = f"{CLOUDFLARE_BASE_URL}{path}?{urlencode({'page': page, 'per_page': PAGE_SIZE})}"
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise CloudflareRetryableError(
                f"Cloudflare API error (retryable): status={response.status_code}, url={url}"
            )

        if not response.ok:
            logger.error(f"Cloudflare API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    def iterate_pages(path: str) -> Iterator[list[dict[str, Any]]]:
        page = 1
        while True:
            body = fetch(path, page)
            items = body.get("result", []) or []
            if items:
                yield items
            total_pages = (body.get("result_info") or {}).get("total_pages")
            if not items or (isinstance(total_pages, int) and page >= total_pages):
                return
            if total_pages is None and len(items) < PAGE_SIZE:
                return
            page += 1

    if not config.zone_scoped:
        yield from iterate_pages(config.path)
        return

    zone_ids = [zone["id"] for page in iterate_pages("/zones") for zone in page if zone.get("id")]
    assert config.parent_key is not None, (
        f"Zone-scoped endpoint '{endpoint}' must define parent_key in CLOUDFLARE_ENDPOINTS"
    )
    for zone_id in zone_ids:
        path = config.path.replace("{zone_id}", quote(zone_id))
        for page_items in iterate_pages(path):
            yield [{**item, config.parent_key: zone_id} for item in page_items]


def cloudflare_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = CLOUDFLARE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
