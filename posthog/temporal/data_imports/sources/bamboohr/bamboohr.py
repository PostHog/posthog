import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.bamboohr.settings import BAMBOOHR_ENDPOINTS, BambooHREndpointConfig
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# BambooHR's API is served through a single gateway host; the company subdomain is a path segment.
# Confirmed live: the gateway returns 401 (not 404) for the v1 paths below, so the route shape is correct.
BAMBOOHR_API_HOST = "https://api.bamboohr.com/api/gateway.php"
# Basic auth uses the API key as the username and any non-empty string as the password.
BAMBOOHR_BASIC_AUTH_PASSWORD = "x"
REQUEST_TIMEOUT_SECONDS = 60
# Time-off endpoints require an explicit window; widen it enough to capture all history and pending future requests.
TIME_OFF_WINDOW_START = "2000-01-01"
TIME_OFF_FUTURE_DAYS = 730


class BambooHRRetryableError(Exception):
    pass


@dataclasses.dataclass
class BambooHRResumeConfig:
    next_url: str


def _base_url(subdomain: str) -> str:
    return f"{BAMBOOHR_API_HOST}/{subdomain}/v1"


def _headers() -> dict[str, str]:
    return {"Accept": "application/json"}


def _auth(api_key: str) -> tuple[str, str]:
    return (api_key, BAMBOOHR_BASIC_AUTH_PASSWORD)


def _build_url(subdomain: str, config: BambooHREndpointConfig) -> str:
    url = f"{_base_url(subdomain)}/{config.path}"
    params: dict[str, str] = {}
    if config.requires_date_window:
        end = (datetime.now(UTC) + timedelta(days=TIME_OFF_FUTURE_DAYS)).strftime("%Y-%m-%d")
        params["start"] = TIME_OFF_WINDOW_START
        params["end"] = end
    if params:
        return f"{url}?{urlencode(params)}"
    return url


def _extract_records(payload: Any, config: BambooHREndpointConfig) -> list[dict[str, Any]]:
    if config.data_key is not None and isinstance(payload, dict):
        payload = payload.get(config.data_key)

    if config.data_shape == "dict":
        # e.g. meta/users returns ``{"<id>": {...}}`` — flatten to the list of records.
        return list(payload.values()) if isinstance(payload, dict) else []

    return payload if isinstance(payload, list) else []


def _next_url(payload: Any) -> str | None:
    """Follow BambooHR's cursor pagination if the response advertises a next page.

    Classic endpoints (directory, meta, time off) return everything in a single response with no
    ``_links``, so this yields once. Cursor-paginated endpoints expose a full URL under ``_links.next``.
    """
    if not isinstance(payload, dict):
        return None
    links = payload.get("_links") or payload.get("links") or {}
    next_link = links.get("next") if isinstance(links, dict) else None
    if isinstance(next_link, str) and next_link.startswith("http"):
        return next_link
    return None


def validate_credentials(subdomain: str, api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Cheap probe against ``meta/fields`` to confirm the subdomain + API key are genuine.

    A 403 means the key is valid but lacks scope for this endpoint — accept it at source-create
    (``schema_name is None``) since users may only grant the scopes they intend to sync.
    """
    url = f"{_base_url(subdomain)}/meta/fields"
    try:
        response = make_tracked_session().get(
            url, auth=_auth(api_key), headers=_headers(), timeout=REQUEST_TIMEOUT_SECONDS
        )
    except Exception:
        return False, "Could not connect to BambooHR. Check the company subdomain and try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid BambooHR API key."
    if response.status_code == 404:
        return False, "BambooHR company subdomain not found. Use the subdomain from your BambooHR URL."
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, "Your BambooHR API key does not have permission to access this data."
    return False, f"BambooHR API returned an unexpected status code: {response.status_code}"


def get_rows(
    subdomain: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BambooHRResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = BAMBOOHR_ENDPOINTS[endpoint]
    headers = _headers()
    auth = _auth(api_key)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url = resume_config.next_url
        logger.debug(f"BambooHR: resuming {endpoint} from URL: {url}")
    else:
        url = _build_url(subdomain, config)

    @retry(
        retry=retry_if_exception_type((BambooHRRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_url: str) -> Any:
        response = make_tracked_session().get(page_url, auth=auth, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise BambooHRRetryableError(
                f"BambooHR API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"BambooHR API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        payload = fetch_page(url)
        records = _extract_records(payload, config)
        next_url = _next_url(payload)

        if records:
            yield records
            # Save state only after yielding so a crash re-yields the last batch (merge dedupes on PK)
            # rather than skipping it.
            if next_url:
                resumable_source_manager.save_state(BambooHRResumeConfig(next_url=next_url))

        if not next_url:
            break

        url = next_url


def bamboohr_source(
    subdomain: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BambooHRResumeConfig],
) -> SourceResponse:
    config = BAMBOOHR_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            subdomain=subdomain,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
    )
