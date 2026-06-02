import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.okta.settings import OKTA_ENDPOINTS, OktaEndpointConfig

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class OktaRetryableError(Exception):
    pass


@dataclasses.dataclass
class OktaResumeConfig:
    next_url: str


def normalize_domain(domain: str) -> str:
    """Turn whatever the user typed into a bare Okta org host.

    Accepts values like ``company.okta.com``, ``https://company.okta.com/``,
    or ``company.okta.com/api/v1`` and returns ``company.okta.com``.
    """
    domain = domain.strip()
    domain = re.sub(r"^https?://", "", domain, flags=re.IGNORECASE)
    domain = domain.split("/")[0]
    return domain.strip().rstrip("/")


def _base_url(domain: str) -> str:
    return f"https://{normalize_domain(domain)}/api/v1"


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"SSWS {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _format_datetime_z(dt: datetime) -> str:
    """Okta wants ISO 8601 with millisecond precision and a literal ``Z`` suffix."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _build_initial_params(
    config: OktaEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": config.page_size}

    if config.name == "logs":
        # The System Log defaults to the last 7 days when `since` is omitted, so on the
        # first sync we explicitly reach back to the start of Okta's retention window.
        params["sortOrder"] = "ASCENDING"
        since_value = db_incremental_field_last_value
        if should_use_incremental_field and not since_value and config.default_lookback_days:
            since_value = datetime.now(UTC) - timedelta(days=config.default_lookback_days)
        if since_value:
            params["since"] = _format_incremental_value(since_value)
        return params

    if config.incremental_param == "filter" and should_use_incremental_field and db_incremental_field_last_value:
        field = incremental_field or config.default_incremental_field
        formatted = _format_incremental_value(db_incremental_field_last_value)
        # Okta's SCIM-style filter expects the value wrapped in double quotes.
        params["filter"] = f'{field} gt "{formatted}"'

    return params


def _build_initial_url(domain: str, config: OktaEndpointConfig, params: dict[str, Any]) -> str:
    url = f"{_base_url(domain)}{config.path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


def _parse_next_url(link_header: str) -> str | None:
    """Return the URL with ``rel="next"`` from Okta's ``Link`` header, if any.

    Note: the System Log endpoint *always* returns a next link (it is designed for
    polling), so callers must also treat an empty page as the end of pagination.
    """
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        match = re.match(r'<([^>]+)>;\s*rel="next"', part)
        if match:
            return match.group(1)
    return None


def validate_credentials(domain: str, api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe a cheap list endpoint to confirm the SSWS token is genuine.

    At source-create (``schema_name is None``) a 403 is accepted: the token is valid but may
    simply lack the scope for this particular probe. A scoped probe (``schema_name`` set) treats
    403 as a hard failure.
    """
    try:
        normalized = normalize_domain(domain)
    except Exception:
        return False, "Invalid Okta domain"

    if not normalized or not re.match(r"^[A-Za-z0-9.\-]+$", normalized):
        return False, "Invalid Okta domain"

    url = f"https://{normalized}/api/v1/users"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), params={"limit": 1}, timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid Okta API token"

    if response.status_code == 403:
        if schema_name is None:
            # Valid token, missing scope for this probe — let source creation through.
            return True, None
        return False, "Okta API token lacks the required permissions for this endpoint"

    try:
        body = response.json()
        return False, body.get("errorSummary", response.text)
    except Exception:
        return False, response.text


def get_rows(
    domain: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OktaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = OKTA_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url: str = resume_config.next_url
        logger.debug(f"Okta: resuming from URL: {url}")
    else:
        url = _build_initial_url(domain, config, params)

    @retry(
        retry=retry_if_exception_type((OktaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_url: str) -> requests.Response:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise OktaRetryableError(f"Okta API error (retryable): status={response.status_code}, url={page_url}")

        if not response.ok:
            logger.error(f"Okta API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response

    while True:
        response = fetch_page(url)

        data = response.json()
        if not isinstance(data, list) or not data:
            break

        next_url = _parse_next_url(response.headers.get("Link", ""))

        # Page and chunk boundaries don't line up, so checkpoint the CURRENT page URL.
        # On resume we re-fetch it and rely on primary-key merge semantics to dedupe rows
        # that were already yielded.
        checkpoint_url = url

        for item in data:
            batcher.batch(item)

            if batcher.should_yield():
                py_table = batcher.get_table()
                yield py_table
                resumable_source_manager.save_state(OktaResumeConfig(next_url=checkpoint_url))

        if not next_url:
            break

        url = next_url

    if batcher.should_yield(include_incomplete_chunk=True):
        py_table = batcher.get_table()
        yield py_table


def okta_source(
    domain: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OktaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = OKTA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            domain=domain,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[endpoint_config.primary_key],
        # Okta returns the System Log ascending (we request sortOrder=ASCENDING). The filter
        # endpoints don't guarantee an order, but each sync re-applies `filter=lastUpdated gt
        # <watermark>` and paginates every page, so completeness doesn't depend on ordering.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
