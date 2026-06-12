import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.personio.settings import PERSONIO_ENDPOINTS, PersonioEndpointConfig

PERSONIO_BASE_URL = "https://api.personio.de"
TOKEN_URL = f"{PERSONIO_BASE_URL}/v2/auth/token"
REQUEST_TIMEOUT_SECONDS = 60
# ~200 req/min per credential (persons 300/min); 429s carry X-RateLimit headers
# but exponential backoff is sufficient.
MAX_RETRY_ATTEMPTS = 5


class PersonioRetryableError(Exception):
    pass


@dataclasses.dataclass
class PersonioResumeConfig:
    # Personio v2 paginates via _meta.links.next.href, a self-contained URL
    # (opaque cursor), so the URL is all we persist.
    next_url: str


def _get_session(client_secret: str) -> requests.Session:
    return make_tracked_session(redact_values=(client_secret,))


def _mint_token(session: requests.Session, client_id: str, client_secret: str) -> str:
    """Exchange client credentials for a bearer token (~24h lifetime)."""
    response = session.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _format_updated_at(value: Any) -> str:
    """Format an incremental cursor for Personio's RFC3339 date-time filters."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _build_initial_url(
    config: PersonioEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str:
    params: dict[str, Any] = {"limit": config.page_size}

    if (
        config.incremental_param is not None
        and should_use_incremental_field
        and db_incremental_field_last_value is not None
    ):
        params[config.incremental_param] = _format_updated_at(db_incremental_field_last_value)

    return f"{PERSONIO_BASE_URL}{config.path}?{urlencode(params)}"


def validate_credentials(client_id: str, client_secret: str) -> bool:
    """Confirm the credentials are valid by minting a token — scopes are
    granted per credential, so a successful mint is the only universal probe."""
    try:
        _mint_token(_get_session(client_secret), client_id, client_secret)
        return True
    except Exception:
        return False


def get_rows(
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PersonioResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PERSONIO_ENDPOINTS[endpoint]
    session = _get_session(client_secret)
    token = _mint_token(session, client_id, client_secret)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url: str = resume_config.next_url
        logger.debug(f"Personio: resuming {endpoint} from URL: {url}")
    else:
        url = _build_initial_url(config, should_use_incremental_field, db_incremental_field_last_value)

    @retry(
        retry=retry_if_exception_type((PersonioRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        nonlocal token
        response = session.get(page_url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS)

        # Tokens last ~24h; re-mint once if the sync outlives one.
        if response.status_code == 401:
            token = _mint_token(session, client_id, client_secret)
            response = session.get(
                page_url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS
            )

        if response.status_code == 429 or response.status_code >= 500:
            raise PersonioRetryableError(
                f"Personio API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Personio API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)
        items = data.get("_data", []) or []

        if items:
            yield items

        next_url = (((data.get("_meta") or {}).get("links") or {}).get("next") or {}).get("href")
        if not next_url or not items:
            break

        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(PersonioResumeConfig(next_url=next_url))
        url = next_url


def personio_source(
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PersonioResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PERSONIO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            client_id=client_id,
            client_secret=client_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
