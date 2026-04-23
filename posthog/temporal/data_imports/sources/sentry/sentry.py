import re
import dataclasses
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import quote, urljoin

import requests
import structlog
from dateutil import parser as dateutil_parser
from requests import Request, Response
from tenacity import RetryCallState, retry, retry_if_exception_type, retry_if_result, stop_after_attempt

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.rest_source.fanout import build_dependent_resource
from posthog.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from posthog.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.sentry.settings import (
    ALLOWED_SENTRY_API_BASE_URLS,
    DEFAULT_SENTRY_API_BASE_URL,
    SENTRY_ENDPOINTS,
    SentryEndpointConfig,
)

_MAX_PAGES_PER_PARENT = 100
_REQUEST_TIMEOUT = 30
_MAX_RETRIES = 3
_RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)
# Safety bound for how many issues the issue_tag_values fan-out will skip while
# fast-forwarding to a saved checkpoint issue. If the checkpoint issue was
# deleted between runs, we'd otherwise skip every remaining issue and yield
# nothing. Once this bound is exceeded we treat the checkpoint as stale and
# fall through to fresh processing of the current and remaining issues.
_RESUME_ISSUE_SKIP_LIMIT = 5000
logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class SentryResumeConfig:
    """Resume state for Sentry endpoints.

    Flat org-level endpoints (projects/teams/members/...) checkpoint the
    ``next_url`` returned by ``SentryPaginator``.

    ``issue_tag_values`` is a three-level hand-rolled fan-out
    (issues -> tags-per-issue -> values-per-tag); its checkpoint is the
    ``(issue_id, tag_key, values_next_url)`` triple pointing at the next
    values page to fetch for that specific (issue, tag) combination.

    Parent/child fan-out endpoints driven by ``build_dependent_resource``
    don't currently checkpoint — the framework does not expose a resume
    hook for dependent resources, so those paths remain non-resumable.
    """

    next_url: Optional[str] = None
    issue_id: Optional[str] = None
    tag_key: Optional[str] = None
    values_next_url: Optional[str] = None


def _normalize_api_base_url(api_base_url: str | None) -> str:
    return (api_base_url or DEFAULT_SENTRY_API_BASE_URL).rstrip("/")


def _validated_api_base_url(api_base_url: str | None) -> str:
    normalized_url = _normalize_api_base_url(api_base_url)
    if normalized_url not in ALLOWED_SENTRY_API_BASE_URLS:
        raise ValueError(
            "API base URL must be one of https://sentry.io, https://us.sentry.io, or https://de.sentry.io."
        )
    return normalized_url


def _auth_headers(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}", "Accept": "application/json"}


def _rest_api_client_config(base_api_url: str, auth_token: str) -> ClientConfig:
    return {
        "base_url": base_api_url,
        "auth": {"type": "bearer", "token": auth_token},
        "headers": {"Accept": "application/json"},
        "paginator": SentryPaginator(),
    }


def _coerce_datetime_to_utc(value: Any) -> datetime | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time())

    if not isinstance(value, datetime):
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _start_param_for_sentry(value: Any) -> str:
    """Format/cap datetime-like values for Sentry `start` and `end` params."""
    normalized_value = _coerce_datetime_to_utc(value)
    if normalized_value is None:
        return str(value)

    capped = min(normalized_value, datetime.now(UTC))
    # Keep format conservative for API parsing: no timezone suffix, second precision.
    return capped.strftime("%Y-%m-%dT%H:%M:%S")


def _sentry_incremental_window(cursor_path: str) -> IncrementalConfig:
    return {
        "cursor_path": cursor_path,
        "start_param": "start",
        "end_param": "end",
        "initial_value": "1970-01-01T00:00:00",
        "end_value": _start_param_for_sentry(datetime.now(UTC)),
        "convert": _start_param_for_sentry,
    }


def _parse_next_link(link_header: str) -> str | None:
    if not link_header:
        return None

    for part in link_header.split(","):
        part = part.strip()
        next_match = re.search(r'<([^>]+)>;\s*rel="next"', part)
        if not next_match:
            continue
        results_match = re.search(r'results="(true|false)"', part)
        if results_match and results_match.group(1) == "true":
            return next_match.group(1)
        return None
    return None


class SentryPaginator(BasePaginator):
    """Paginator for Sentry API Link-header cursor pagination."""

    def __init__(self) -> None:
        super().__init__()
        self._next_url: str | None = None

    def init_request(self, request: Request) -> None:
        # When seeded via ``set_resume_state``, the paginator already holds the
        # URL of the next page to fetch; redirect the first request to it so we
        # don't re-issue the initial page before resuming.
        if self._next_url:
            request.url = self._next_url
            request.params = {}

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        link_header = response.headers.get("Link", "")
        self._next_url = _parse_next_link(link_header)
        self._has_next_page = self._next_url is not None

    def update_request(self, request: Request) -> None:
        if self._next_url:
            request.url = self._next_url
            request.params = {}

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._next_url and self._has_next_page:
            return {"next_url": self._next_url}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_url = state.get("next_url")
        if next_url:
            self._next_url = next_url
            self._has_next_page = True


# ---------------------------------------------------------------------------
# Low-level HTTP helpers (used only by issue_tag_values custom fan-out)
# ---------------------------------------------------------------------------


def _is_retryable_response(response: requests.Response) -> bool:
    return response.status_code in _RETRYABLE_STATUS_CODES


def _retry_wait_seconds(state: RetryCallState) -> float:
    fallback_wait = min(2 ** (state.attempt_number - 1), 30)
    if state.outcome is None or state.outcome.failed:
        return float(fallback_wait)

    response = state.outcome.result()
    if response.status_code != 429:
        return float(fallback_wait)

    reset_header = response.headers.get("X-Sentry-Rate-Limit-Reset")
    if not reset_header:
        return float(fallback_wait)

    try:
        reset_epoch = int(reset_header)
    except ValueError:
        return float(fallback_wait)

    wait_until_reset = reset_epoch - int(datetime.now(UTC).timestamp())
    if wait_until_reset <= 0:
        return float(fallback_wait)

    return float(wait_until_reset)


def _raise_on_failed_retry(state: RetryCallState) -> requests.Response:
    if state.outcome is None:
        raise RuntimeError("Unexpected request retry state")
    if state.outcome.failed:
        exc = state.outcome.exception()
        if exc is None:
            raise RuntimeError("Unexpected request retry state")
        raise exc
    return state.outcome.result()


@retry(
    stop=stop_after_attempt(_MAX_RETRIES + 1),
    wait=_retry_wait_seconds,
    retry=retry_if_exception_type(requests.exceptions.RequestException) | retry_if_result(_is_retryable_response),
    retry_error_callback=_raise_on_failed_retry,
)
def _request_with_retry(
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    timeout: int = _REQUEST_TIMEOUT,
) -> requests.Response:
    return requests.get(url, headers=headers, params=params, timeout=timeout)


def _iter_endpoint_rows(
    base_api_url: str,
    path: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    max_pages: int | None = None,
) -> Iterator[dict[str, Any]]:
    url = urljoin(f"{base_api_url}/", path.lstrip("/"))
    current_params: dict[str, Any] | None = params if params is not None else {}
    pages_read = 0
    max_pages_to_read = max_pages if max_pages and max_pages > 0 else None

    while url:
        if max_pages_to_read is not None and pages_read >= max_pages_to_read:
            if max_pages_to_read == _MAX_PAGES_PER_PARENT:
                logger.info(
                    "sentry_source.max_pages_per_parent_reached",
                    resource_path=path,
                    max_pages_per_parent=_MAX_PAGES_PER_PARENT,
                )
            break

        response = _request_with_retry(url=url, headers=headers, params=current_params)
        response.raise_for_status()

        payload = response.json()
        yield from payload

        pages_read += 1
        next_url = _parse_next_link(response.headers.get("Link", ""))
        if not next_url:
            break
        url = urljoin(f"{base_api_url}/", next_url)
        current_params = None


def _parse_datetime_value(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            parsed_value = dateutil_parser.parse(value)
        except (ValueError, TypeError):
            return None
        return _coerce_datetime_to_utc(parsed_value)
    return _coerce_datetime_to_utc(value)


# ---------------------------------------------------------------------------
# Issue tag-values fan-out (custom iterator — requires two-level fan-out:
# issues → tags-per-issue → values-per-tag.  Can't be expressed as a single
# parent→child dependency in rest_api_resources.)
# ---------------------------------------------------------------------------


def _iter_issue_tag_values_rows(
    base_api_url: str,
    headers: dict[str, str],
    organization_slug: str,
    resumable_source_manager: Optional[ResumableSourceManager[SentryResumeConfig]] = None,
    incremental_last_seen_max: Any = None,
) -> Iterator[dict[str, Any]]:
    cutoff_last_seen = _parse_datetime_value(incremental_last_seen_max)

    # Resume state only honours the fan-out fields; the flat-endpoint
    # ``next_url`` is meaningless here. We require the full (issue_id, tag_key,
    # values_next_url) triple to be present — anything partial is treated as
    # absent and falls through to a fresh run so we don't apply a stale URL to
    # the wrong (issue, tag) pair.
    resume_issue_id: str | None = None
    resume_tag_key: str | None = None
    resume_values_next_url: str | None = None
    if resumable_source_manager is not None and resumable_source_manager.can_resume():
        loaded = resumable_source_manager.load_state()
        if loaded is not None and loaded.issue_id and loaded.tag_key and loaded.values_next_url:
            resume_issue_id = loaded.issue_id
            resume_tag_key = loaded.tag_key
            resume_values_next_url = loaded.values_next_url

    issues = _iter_endpoint_rows(
        base_api_url=base_api_url,
        path=f"/organizations/{organization_slug}/issues/",
        headers=headers,
        params={"limit": 100, "query": "", "sort": "date"},
    )

    skipped_for_resume = 0

    for issue in issues:
        if cutoff_last_seen is not None:
            issue_last_seen = _parse_datetime_value(issue.get("lastSeen"))
            if issue_last_seen is not None and issue_last_seen <= cutoff_last_seen:
                break

        issue_id = str(issue["id"])

        # Fast-forward until we reach the saved checkpoint issue. We rely on
        # the deterministic sort=date ordering to land back on the same issue.
        # If the checkpoint issue has been deleted we could skip forever, so
        # bound the skip count and fall through to a fresh run when exceeded.
        if resume_issue_id is not None and issue_id != resume_issue_id:
            skipped_for_resume += 1
            if skipped_for_resume > _RESUME_ISSUE_SKIP_LIMIT:
                logger.info(
                    "sentry_source.stale_resume_checkpoint",
                    resume_issue_id=resume_issue_id,
                    skipped=skipped_for_resume,
                )
                resume_issue_id = None
                resume_tag_key = None
                resume_values_next_url = None
                # Fall through: process the current issue and subsequent ones fresh.
            else:
                continue

        # Mark that we've found the checkpoint issue. If the checkpoint tag has
        # since disappeared, we still exit the middle loop with no match — clear
        # outer fast-forward state at the end of this iteration so subsequent
        # issues run fresh instead of being skipped forever.
        matched_checkpoint_issue = resume_issue_id is not None

        tags = _iter_endpoint_rows(
            base_api_url=base_api_url,
            path=f"/organizations/{organization_slug}/issues/{issue_id}/tags/",
            headers=headers,
            params={"limit": 100},
            max_pages=_MAX_PAGES_PER_PARENT,
        )
        for tag in tags:
            tag_key = tag.get("key") or tag.get("id")
            if not isinstance(tag_key, str) or not tag_key:
                continue

            if resume_issue_id is not None and resume_tag_key is not None and tag_key != resume_tag_key:
                continue

            values_path = f"/organizations/{organization_slug}/issues/{issue_id}/tags/{quote(tag_key, safe='')}/values/"
            if resume_issue_id is not None and resume_values_next_url:
                values_url: str = resume_values_next_url
                values_params: dict[str, Any] | None = None
            else:
                values_url = urljoin(f"{base_api_url}/", values_path.lstrip("/"))
                values_params = {"limit": 100, "sort": "-date"}
            pages_read = 0

            # Clear resume markers so the NEXT (issue, tag) pair runs fresh.
            resume_issue_id = None
            resume_tag_key = None
            resume_values_next_url = None

            while values_url:
                if pages_read >= _MAX_PAGES_PER_PARENT:
                    logger.info(
                        "sentry_source.max_pages_per_parent_reached",
                        resource_path=values_path,
                        organization_slug=organization_slug,
                        issue_id=issue_id,
                        tag_key=tag_key,
                        max_pages_per_parent=_MAX_PAGES_PER_PARENT,
                    )
                    break

                response = _request_with_retry(url=values_url, headers=headers, params=values_params)
                response.raise_for_status()
                rows = response.json()

                should_stop = False
                for row in rows:
                    if cutoff_last_seen is not None:
                        row_last_seen = _parse_datetime_value(row.get("lastSeen"))
                        if row_last_seen is not None and row_last_seen <= cutoff_last_seen:
                            should_stop = True
                            break

                    row["issue_id"] = issue_id
                    row["tag_key"] = tag_key
                    yield row

                pages_read += 1
                if should_stop:
                    break

                next_url = _parse_next_link(response.headers.get("Link", ""))

                # Checkpoint the URL of the NEXT values page — it has not been
                # fetched yet, so resume can pick it up directly without
                # re-processing any rows that were already yielded.
                if next_url and resumable_source_manager is not None:
                    resumable_source_manager.save_state(
                        SentryResumeConfig(
                            issue_id=issue_id,
                            tag_key=tag_key,
                            values_next_url=urljoin(f"{base_api_url}/", next_url),
                        )
                    )

                if not next_url:
                    break
                values_url = urljoin(f"{base_api_url}/", next_url)
                values_params = None

        if matched_checkpoint_issue:
            resume_issue_id = None
            resume_tag_key = None
            resume_values_next_url = None


# ---------------------------------------------------------------------------
# Credential validation
# ---------------------------------------------------------------------------


def validate_credentials(
    auth_token: str,
    organization_slug: str,
    api_base_url: str | None = None,
) -> tuple[bool, str | None]:
    try:
        base_url = _validated_api_base_url(api_base_url)
    except ValueError as exc:
        return False, str(exc)

    url = f"{base_url}/api/0/organizations/{organization_slug}/projects/"
    headers = _auth_headers(auth_token)

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return True, None
        if response.status_code == 401:
            return False, "Invalid Sentry auth token"
        if response.status_code == 403:
            return False, "Sentry token is missing required scopes"
        if response.status_code == 404:
            return False, f"Sentry organization '{organization_slug}' not found"

        try:
            return False, response.json().get("detail", response.text)
        except Exception:
            return False, response.text
    except requests.exceptions.RequestException as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Resource config builder (org-level flat endpoints only)
# ---------------------------------------------------------------------------


def get_resource(
    endpoint: str,
    organization_slug: str,
    should_use_incremental_field: bool,
    incremental_field: str | None = None,
) -> EndpointResource:
    config = SENTRY_ENDPOINTS[endpoint]
    if config.fanout or endpoint == "issue_tag_values":
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    params: dict[str, Any] = {"limit": config.page_size}

    endpoint_config: Endpoint = {
        "path": config.path.format(organization_slug=organization_slug),
        "params": params,
    }

    if endpoint == "issues":
        params["query"] = ""
        params["sort"] = "date" if (incremental_field or config.default_incremental_field) == "lastSeen" else "new"
        if should_use_incremental_field and config.incremental_fields:
            endpoint_config["incremental"] = _sentry_incremental_window(
                incremental_field or config.default_incremental_field or "lastSeen"
            )

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field and config.incremental_fields
        else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_source_response(endpoint_config: SentryEndpointConfig, items_fn) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_key
        if isinstance(endpoint_config.primary_key, list)
        else [endpoint_config.primary_key],
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


# ---------------------------------------------------------------------------
# Main entry point — routes each endpoint to the right extraction strategy
# ---------------------------------------------------------------------------


def sentry_source(
    auth_token: str,
    organization_slug: str,
    api_base_url: str | None,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: Optional[ResumableSourceManager[SentryResumeConfig]] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = SENTRY_ENDPOINTS[endpoint]
    normalized_base_url = _validated_api_base_url(api_base_url)
    base_api_url = f"{normalized_base_url}/api/0"

    # issue_tag_values needs two-level fan-out (issues → tags → values)
    # which can't be expressed as a single parent→child dependency.
    if endpoint == "issue_tag_values":
        headers = _auth_headers(auth_token)
        return _make_source_response(
            endpoint_config,
            lambda: _iter_issue_tag_values_rows(
                base_api_url=base_api_url,
                headers=headers,
                organization_slug=organization_slug,
                resumable_source_manager=resumable_source_manager,
                incremental_last_seen_max=db_incremental_field_last_value if should_use_incremental_field else None,
            ),
        )

    # --- Generic parent->child fan-out ---
    # Dependent resources don't currently support resume in the rest_source
    # framework; the manager is intentionally not threaded into this path.
    if endpoint_config.fanout:
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=SENTRY_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=endpoint_config.fanout,
                client_config=_rest_api_client_config(base_api_url, auth_token),
                path_format_values={"organization_slug": organization_slug},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
                incremental_config_factory=_sentry_incremental_window,
            ),
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    # --- Flat org-level endpoints (via rest_api_resources) ---
    config: RESTAPIConfig = {
        "client": _rest_api_client_config(base_api_url, auth_token),
        "resource_defaults": {
            "write_disposition": "replace",
            "endpoint": {"params": {"limit": endpoint_config.page_size}},
        },
        "resources": [
            get_resource(
                endpoint=endpoint,
                organization_slug=organization_slug,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
            )
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None
    if resumable_source_manager is not None:
        if resumable_source_manager.can_resume():
            resume_config = resumable_source_manager.load_state()
            if resume_config is not None and resume_config.next_url:
                initial_paginator_state = {"next_url": resume_config.next_url}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Match klaviyo/reddit_ads: persist only while there is another
            # page to resume to. Redis TTL cleans up on completion.
            if state and state.get("next_url") and resumable_source_manager is not None:
                resumable_source_manager.save_state(SentryResumeConfig(next_url=state["next_url"]))

        resume_hook = save_checkpoint

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(endpoint_config, lambda: resource)
