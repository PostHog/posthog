import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.resend.settings import RESEND_ENDPOINTS, ResendEndpointConfig

RESEND_BASE_URL = "https://api.resend.com"
_EMAILS_DEFAULT_PAGE_SIZE = 100


class ResendRetryableError(Exception):
    pass


@dataclasses.dataclass
class ResendResumeConfig:
    # Cursor for the /emails endpoint (Resend's `after` parameter).
    next_cursor: Optional[str] = None
    # For fan-out endpoints: the parent id we last finished processing, so we can
    # skip completed parents on resume.
    last_completed_parent_id: Optional[str] = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def validate_credentials(api_key: str) -> bool:
    # /domains is a cheap read-only call that requires a valid API key with at
    # least read scope — Resend returns 401 for bad keys and 200 for good ones.
    url = f"{RESEND_BASE_URL}/domains"
    try:
        response = requests.get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type((ResendRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(url: str, headers: dict[str, str], params: Optional[dict[str, Any]], logger: FilteringBoundLogger) -> dict:
    response = requests.get(url, headers=headers, params=params, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise ResendRetryableError(f"Resend API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Resend API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_flat_endpoint(
    api_key: str,
    config: ResendEndpointConfig,
    logger: FilteringBoundLogger,
    path: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    """Fetch a non-paginated list endpoint that returns {"data": [...]} once."""
    url = f"{RESEND_BASE_URL}{path or config.path}"
    data = _fetch(url, _get_headers(api_key), None, logger)
    items = data.get("data") or []
    if items:
        yield items


def _iter_emails(
    api_key: str,
    config: ResendEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ResendResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Iterate the /emails endpoint using Resend's cursor pagination (limit + after)."""
    headers = _get_headers(api_key)
    url = f"{RESEND_BASE_URL}{config.path}"
    page_size = config.page_size or _EMAILS_DEFAULT_PAGE_SIZE

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor: Optional[str] = resume_config.next_cursor if resume_config else None
    if cursor:
        logger.debug(f"Resend: resuming /emails from cursor={cursor}")

    while True:
        params: dict[str, Any] = {"limit": page_size}
        if cursor:
            params["after"] = cursor

        data = _fetch(url, headers, params, logger)
        items = data.get("data") or []
        has_more = bool(data.get("has_more"))

        if items:
            yield items

        if not has_more:
            break
        if not items:
            # has_more=True with an empty page would silently skip remaining
            # rows; surface it instead of producing a data gap.
            raise ValueError(f"Resend API returned an empty page but has_more=True for {url}")

        # Advance cursor from the last row's id (Resend keyset pagination on id).
        # Use direct access so a missing id surfaces as a hard error rather than
        # silently terminating pagination and producing a data gap.
        cursor = items[-1]["id"]
        resumable_source_manager.save_state(ResendResumeConfig(next_cursor=cursor))


def _iter_contacts_fanout(
    api_key: str,
    config: ResendEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ResendResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """For each audience, fetch its contacts and inject `_audience_id` onto each row."""
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    skip_until: Optional[str] = resume_config.last_completed_parent_id if resume_config else None

    audiences_config = RESEND_ENDPOINTS[config.parent] if config.parent else None
    if audiences_config is None:
        raise ValueError(f"Resend endpoint {config.name} has no parent configured")

    audiences_data = _fetch(f"{RESEND_BASE_URL}{audiences_config.path}", _get_headers(api_key), None, logger)
    audiences = audiences_data.get("data") or []

    # Resume at the audience after the last completed one. If the last completed audience
    # no longer exists (e.g. deleted between syncs) we fall back to a full resync rather
    # than silently skipping every audience and losing all new ones.
    start_idx = 0
    if skip_until is not None:
        found_idx = next((i for i, aud in enumerate(audiences) if aud.get("id") == skip_until), None)
        if found_idx is not None:
            start_idx = found_idx + 1
        else:
            logger.warning(
                f"Resend contacts: last completed audience {skip_until} not found in current audiences, "
                "resuming from the start"
            )

    for audience in audiences[start_idx:]:
        audience_id = audience["id"]

        path = config.path.replace("{audience_id}", audience_id)
        for batch in _iter_flat_endpoint(api_key, config, logger, path=path):
            for row in batch:
                row["_audience_id"] = audience_id
            yield batch

        resumable_source_manager.save_state(ResendResumeConfig(last_completed_parent_id=audience_id))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ResendResumeConfig],
) -> Iterator[Any]:
    config = RESEND_ENDPOINTS[endpoint]
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    if endpoint == "emails":
        source_iter = _iter_emails(api_key, config, logger, resumable_source_manager)
    elif config.parent is not None:
        source_iter = _iter_contacts_fanout(api_key, config, logger, resumable_source_manager)
    else:
        source_iter = _iter_flat_endpoint(api_key, config, logger)

    for batch in source_iter:
        batcher.batch(batch)
        if batcher.should_yield():
            yield batcher.get_table()

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def resend_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ResendResumeConfig],
) -> SourceResponse:
    endpoint_config = RESEND_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[endpoint_config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
