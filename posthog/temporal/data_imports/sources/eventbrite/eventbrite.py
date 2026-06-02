import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.eventbrite.settings import (
    EVENTBRITE_ENDPOINTS,
    ORG_EVENTS_PATH,
    ORGANIZATIONS_PATH,
    EndpointScope,
    EventbriteEndpointConfig,
)

EVENTBRITE_BASE_URL = "https://www.eventbriteapi.com/v3"


class EventbriteRetryableError(Exception):
    pass


@dataclasses.dataclass
class EventbriteResumeConfig:
    # Continuation token for the next page. Only persisted for top-level endpoints — fan-out
    # endpoints restart from the first parent on resume and rely on merge dedupe (same as Stripe's
    # nested-resource handling), since parent ordering is not guaranteed stable.
    continuation: str


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _format_changed_since(value: Any) -> str:
    """Format an incremental value for Eventbrite's `changed_since` filter (ISO 8601 UTC, Z suffix)."""
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def validate_credentials(api_token: str) -> bool:
    url = f"{EVENTBRITE_BASE_URL}/users/me/"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_token), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type((EventbriteRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=60)

    # Eventbrite enforces a strict per-token rate limit; honor it via retry/backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise EventbriteRetryableError(f"Eventbrite API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Eventbrite API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_pages(
    session: requests.Session,
    url: str,
    base_params: dict[str, Any],
    data_key: str,
    logger: FilteringBoundLogger,
    start_continuation: Optional[str] = None,
) -> Iterator[tuple[dict[str, Any], Optional[str]]]:
    """Yield (record, next_continuation) across continuation-token pages of a single list endpoint.

    `next_continuation` is the token that fetches the page *after* the one the record came from
    (or None on the last page) — callers persisting resume state save it right after yielding.
    """
    continuation = start_continuation
    while True:
        params = dict(base_params)
        if continuation:
            params["continuation"] = continuation

        data = _fetch_page(session, url, params, logger)
        items = data.get(data_key, []) or []
        pagination = data.get("pagination") or {}
        next_continuation = pagination.get("continuation") if pagination.get("has_more_items") else None

        for item in items:
            yield item, next_continuation

        if not next_continuation:
            break
        continuation = next_continuation


def _iter_organization_ids(session: requests.Session, logger: FilteringBoundLogger) -> Iterator[str]:
    url = f"{EVENTBRITE_BASE_URL}{ORGANIZATIONS_PATH}"
    for org, _ in _iter_pages(session, url, {}, "organizations", logger):
        # Fail fast on a malformed response rather than silently dropping all of an org's children.
        yield str(org["id"])


def _iter_event_ids(session: requests.Session, logger: FilteringBoundLogger) -> Iterator[str]:
    for org_id in _iter_organization_ids(session, logger):
        url = f"{EVENTBRITE_BASE_URL}{ORG_EVENTS_PATH.format(organization_id=org_id)}"
        for event, _ in _iter_pages(session, url, {}, "events", logger):
            yield str(event["id"])


def _iter_records(
    session: requests.Session,
    config: EventbriteEndpointConfig,
    logger: FilteringBoundLogger,
    changed_since: Optional[str],
    resume: Optional[EventbriteResumeConfig],
) -> Iterator[tuple[dict[str, Any], Optional[str]]]:
    base_params: dict[str, Any] = {}
    if changed_since:
        base_params["changed_since"] = changed_since

    if config.scope == EndpointScope.TOP_LEVEL:
        url = f"{EVENTBRITE_BASE_URL}{config.path}"
        start = resume.continuation if resume else None
        yield from _iter_pages(session, url, base_params, config.data_key, logger, start_continuation=start)
        return

    if config.scope == EndpointScope.ORG:
        parent_ids = _iter_organization_ids(session, logger)
        placeholder = "organization_id"
    else:
        parent_ids = _iter_event_ids(session, logger)
        placeholder = "event_id"

    # Fan-out: paginate the child endpoint per parent. We never persist a resume token here, so
    # downstream always sees next_continuation=None for these records.
    for parent_id in parent_ids:
        url = f"{EVENTBRITE_BASE_URL}{config.path.format(**{placeholder: parent_id})}"
        for record, _ in _iter_pages(session, url, base_params, config.data_key, logger):
            yield record, None


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EventbriteResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = EVENTBRITE_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_get_headers(api_token))
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    # Only narrow with the server-side `changed_since` filter when the endpoint supports it and the
    # user's chosen cursor is the field that filter targets (`changed`). Honors inputs.incremental_field
    # rather than assuming it.
    changed_since: Optional[str] = None
    if (
        should_use_incremental_field
        and config.changed_since_field
        and db_incremental_field_last_value
        and incremental_field in (None, config.changed_since_field)
    ):
        changed_since = _format_changed_since(db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        logger.debug(f"Eventbrite: resuming {endpoint} from continuation token")

    for record, next_continuation in _iter_records(session, config, logger, changed_since, resume):
        batcher.batch(record)

        if batcher.should_yield():
            yield batcher.get_table()

            # Save state after yielding so a crash re-yields the last batch (merge dedupes on PK).
            if next_continuation:
                resumable_source_manager.save_state(EventbriteResumeConfig(continuation=next_continuation))

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def eventbrite_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EventbriteResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = EVENTBRITE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
