from collections.abc import AsyncIterable, Callable, Iterable, Iterator
from typing import Any, Optional

import structlog
from requests import Request, Response, Session
from requests.exceptions import HTTPError
from urllib3.util.retry import Retry

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import DEFAULT_RETRY, make_tracked_session
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    SinglePagePaginator,
)
from posthog.temporal.data_imports.sources.common.rest_source.typing import Endpoint, EndpointResource
from posthog.temporal.data_imports.sources.intercom.settings import INTERCOM_ENDPOINTS, IntercomEndpointConfig

INTERCOM_API_BASE = "https://api.intercom.io"
INTERCOM_API_VERSION = "2.13"

logger = structlog.get_logger(__name__)


def _is_not_found(exc: HTTPError) -> bool:
    """A child row referenced by a parent can vanish (deleted/merged) between
    the parent listing and the per-row detail fetch — Intercom then returns
    404. Skip that single row instead of failing the whole sync."""
    return exc.response is not None and exc.response.status_code == 404


def _default_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Intercom-Version": INTERCOM_API_VERSION,
    }


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", **_default_headers()}


# The substream walk reaches `/conversations/search` and `/companies/list` via
# POST. The shared `DEFAULT_RETRY` excludes POST from `allowed_methods`, so a
# transient read timeout on those calls is *not* retried — unlike the GET calls
# in the same walk, which retry transparently. These POSTs are read-only,
# idempotent queries (the body just carries the query + cursor), so it's safe to
# retry them on transient read timeouts and 429/5xx like everything else.
# Derived from DEFAULT_RETRY so the shared policy stays the single source of
# truth — the only intentional difference is adding POST to allowed_methods.
_INTERCOM_RETRY = Retry(
    total=DEFAULT_RETRY.total,
    backoff_factor=DEFAULT_RETRY.backoff_factor,
    status_forcelist=DEFAULT_RETRY.status_forcelist,
    allowed_methods=frozenset(DEFAULT_RETRY.allowed_methods or ()) | {"POST"},
    raise_on_status=DEFAULT_RETRY.raise_on_status,
)


def _make_intercom_session(access_token: str) -> Session:
    """Build a tracked session with Intercom auth + default headers baked in.

    Reusing one session across the many requests a sync makes lets urllib3
    keep the underlying TCP+TLS connection alive — the substream generators
    (one GET per parent row) are the main beneficiary.
    """
    return make_tracked_session(headers=_auth_headers(access_token), retry=_INTERCOM_RETRY)


class IntercomSearchPaginator(BasePaginator):
    """Paginator for Intercom POST `/<resource>/search` endpoints.

    Intercom's search APIs put the pagination cursor in the request body
    (``pagination.starting_after``) rather than the query string, so the
    standard ``JSONResponseCursorPaginator`` — which writes to
    ``request.params`` — doesn't fit. The next cursor is read from
    ``pages.next.starting_after`` in the response, the same shape the list
    endpoints use.
    """

    def __init__(self) -> None:
        super().__init__()
        self._next_cursor: Optional[str] = None

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            payload = response.json()
        except Exception:
            self._has_next_page = False
            self._next_cursor = None
            return
        next_block = (payload.get("pages") or {}).get("next") or {}
        cursor = next_block.get("starting_after") if isinstance(next_block, dict) else None
        if cursor:
            self._next_cursor = cursor
            self._has_next_page = True
        else:
            self._next_cursor = None
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._next_cursor is None or request.json is None:
            return
        pagination = request.json.setdefault("pagination", {})
        pagination["starting_after"] = self._next_cursor


def _build_search_body(
    cfg: IntercomEndpointConfig,
    incremental_field: str,
    db_incremental_field_last_value: Optional[Any],
) -> dict[str, Any]:
    """Build the POST body for Intercom's ``/<resource>/search`` endpoints.

    ``value: 0`` is the historical-backfill case (matches every record);
    once we have a watermark from a prior sync we filter ``<field> > <ts>``.
    Sorting ascending on the same field so the cursor advances monotonically
    — without it Intercom returns by relevance and the watermark we persist
    would be meaningless.
    """
    cursor_value = int(db_incremental_field_last_value) if db_incremental_field_last_value is not None else 0
    return {
        "query": {"field": incremental_field, "operator": ">", "value": cursor_value},
        "pagination": {"per_page": cfg.page_size},
        "sort": {"field": incremental_field, "order": "ascending"},
    }


def _build_paginator(cfg: IntercomEndpointConfig) -> BasePaginator:
    if cfg.paginator_kind == "search":
        return IntercomSearchPaginator()
    if cfg.paginator_kind == "cursor":
        return JSONResponseCursorPaginator(
            cursor_path="pages.next.starting_after",
            cursor_param="starting_after",
        )
    if cfg.paginator_kind == "next_url":
        return JSONResponsePaginator(next_url_path="pages.next")
    return SinglePagePaginator()


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    incremental_field: str | None,
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    cfg = INTERCOM_ENDPOINTS[name]

    endpoint: Endpoint = {
        "path": cfg.path,
        "data_selector": cfg.data_selector,
        "paginator": _build_paginator(cfg),
    }

    if cfg.method == "POST":
        endpoint["method"] = "POST"

    if cfg.paginator_kind == "search":
        # Even in full-refresh mode the search endpoints need a query body;
        # `value: 0` matches every record. Default to "updated_at" (the only
        # cursor Intercom search endpoints support) when no field is passed.
        endpoint["json"] = _build_search_body(cfg, incremental_field or "updated_at", db_incremental_field_last_value)
    elif cfg.method == "POST" and cfg.paginator_kind in ("cursor", "next_url"):
        # POST list endpoints (`/companies/list`) take `per_page` in the body.
        # The next-URL paginator preserves the POST method and body when it
        # follows `pages.next`, so the body just needs to be set once.
        endpoint["json"] = {"per_page": cfg.page_size}
    elif cfg.paginator_kind in ("cursor", "next_url"):
        params: dict[str, Any] = {"per_page": cfg.page_size, **cfg.extra_params}
        if cfg.incremental_query_param:
            # Intercom's `/admins/activity_logs` returns a much smaller default
            # window when called without `created_at_after`, so we always set
            # the param. `0` matches every record (Unix epoch start).
            if should_use_incremental_field and db_incremental_field_last_value is not None:
                params[cfg.incremental_query_param] = int(db_incremental_field_last_value)
            else:
                params[cfg.incremental_query_param] = 0
        endpoint["params"] = params
    elif cfg.paginator_kind == "single" and cfg.extra_params:
        endpoint["params"] = dict(cfg.extra_params)

    # Upsert on incremental syncs so updates to existing rows replace the
    # prior version instead of appending duplicates. Full-refresh endpoints
    # stay on replace.
    is_incremental = should_use_incremental_field and (
        cfg.paginator_kind == "search" or cfg.incremental_query_param is not None
    )
    write_disposition: Any = {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace"

    return {
        "name": cfg.name,
        "table_name": cfg.name,
        "write_disposition": write_disposition,
        "endpoint": endpoint,
        "table_format": "delta",
    }


def _resolve_intercom_url(path_or_url: str) -> str:
    """Accept either an API path or a full URL (e.g. a `pages.next` link)."""
    return path_or_url if path_or_url.startswith("http") else f"{INTERCOM_API_BASE}{path_or_url}"


def _intercom_get(session: Session, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = session.get(_resolve_intercom_url(path_or_url), params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def _intercom_post(session: Session, path_or_url: str, body: dict[str, Any]) -> dict[str, Any]:
    response = session.post(_resolve_intercom_url(path_or_url), json=body, timeout=30)
    response.raise_for_status()
    return response.json()


def _iter_conversations(
    session: Session,
    incremental_field: str,
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[dict[str, Any]]:
    """Walk `POST /conversations/search` honoring the same `updated_at >`
    server-side filter the conversations endpoint uses, so substreams only
    refetch parents whose timestamp advanced."""
    body = _build_search_body(INTERCOM_ENDPOINTS["conversations"], incremental_field, db_incremental_field_last_value)
    while True:
        payload = _intercom_post(session, "/conversations/search", body)
        yield from (payload.get("conversations") or [])
        next_block = (payload.get("pages") or {}).get("next") or {}
        cursor = next_block.get("starting_after") if isinstance(next_block, dict) else None
        if not cursor:
            return
        body["pagination"]["starting_after"] = cursor


def _conversation_parts_generator(
    session: Session,
    incremental_field: str,
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[dict[str, Any]]:
    """Yield each conversation part. Parents are server-filtered by
    `updated_at >`; the part rows themselves carry their own `updated_at`,
    so the pipeline's cursor watermark advances per-part. `conversation_id`
    is injected onto each row for joinability."""
    for conv in _iter_conversations(session, incremental_field, db_incremental_field_last_value):
        try:
            full = _intercom_get(session, f"/conversations/{conv['id']}")
        except HTTPError as exc:
            if _is_not_found(exc):
                logger.warning("intercom_conversation_not_found", conversation_id=conv["id"])
                continue
            raise
        parts = (full.get("conversation_parts") or {}).get("conversation_parts") or []
        for part in parts:
            part["conversation_id"] = conv["id"]
            yield part


def _iter_companies(session: Session) -> Iterator[dict[str, Any]]:
    """Walk every company via `GET /companies/scroll` (full refresh).

    `POST /companies/list` is hard-capped at 10,000 companies — paging past
    that ceiling makes Intercom return `400 bad_request: page limit reached,
    please use scroll API`. The Scroll API has no such ceiling: each response
    carries a `scroll_param` to feed into the next request, and the walk ends
    when `data` comes back empty (the scroll param then expires). Only one
    scroll can be open per workspace at a time — fine here, since this is the
    sole scroll user and a schema never syncs concurrently with itself."""
    scroll_param: str | None = None
    while True:
        params = {"scroll_param": scroll_param} if scroll_param else None
        payload = _intercom_get(session, "/companies/scroll", params=params)
        data = payload.get("data") or []
        if not data:
            return
        yield from data
        scroll_param = payload.get("scroll_param")
        if not scroll_param:
            return


def _company_segments_generator(session: Session) -> Iterator[dict[str, Any]]:
    """Walk all companies and yield each attached segment with `company_id`
    injected. Full refresh — Intercom has no server-side timestamp filter on
    either parent or child."""
    for company in _iter_companies(session):
        try:
            payload = _intercom_get(session, f"/companies/{company['id']}/segments")
        except HTTPError as exc:
            if _is_not_found(exc):
                logger.warning("intercom_company_not_found", company_id=company["id"])
                continue
            raise
        for seg in payload.get("data", []) or []:
            seg["company_id"] = company["id"]
            yield seg


def _substream_items(
    session: Session,
    endpoint: str,
    incremental_field: str | None,
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[dict[str, Any]]:
    if endpoint == "conversation_parts":
        if not incremental_field:
            # Substream still works without an incremental field — we just
            # walk every conversation. `updated_at` is the only declared
            # cursor, so default to it for the parent search filter.
            incremental_field = "updated_at"
        return _conversation_parts_generator(session, incremental_field, db_incremental_field_last_value)
    if endpoint == "company_segments":
        return _company_segments_generator(session)
    raise ValueError(f"Unknown Intercom substream endpoint: {endpoint}")


def validate_credentials(access_token: str, schema_name: str | None = None) -> tuple[bool, str | None]:
    """Validate an Intercom access token by hitting `/me`.

    Works identically with OAuth-issued access tokens and Personal Access
    Tokens — both flow as `Authorization: Bearer …`.

    At source-create (``schema_name is None``) we accept 403 — the token
    is genuine but the workspace hasn't granted scope for ``/me``. The
    user can still grant scope per-endpoint downstream. Per-schema calls
    (``schema_name`` set) re-raise 403 so the missing-scope error
    surfaces against the specific table the user tried to use.
    """
    if not access_token:
        return False, "Missing Intercom access token"

    try:
        response = _make_intercom_session(access_token).get(
            f"{INTERCOM_API_BASE}/me",
            timeout=10,
        )
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Your Intercom access token is invalid or expired. Please reconnect."
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, "Your Intercom access token is missing required scopes. Please reconnect."
    return False, f"HTTP {response.status_code}: {response.text[:200]}"


def intercom_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    incremental_field: str | None = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    cfg = INTERCOM_ENDPOINTS[endpoint]
    items: Callable[[], Iterable[Any] | AsyncIterable[Any]]

    if cfg.paginator_kind == "substream":
        # One session built here is reused across the parent walk and every
        # per-row child fetch, so urllib3 keeps the connection alive instead
        # of re-handshaking per request.
        session = _make_intercom_session(access_token)
        items = lambda: _substream_items(session, endpoint, incremental_field, db_incremental_field_last_value)
    else:
        config: RESTAPIConfig = {
            "client": {
                "base_url": INTERCOM_API_BASE,
                "auth": {
                    "type": "bearer",
                    "token": access_token,
                },
                "headers": _default_headers(),
            },
            "resource_defaults": {},
            "resources": [
                get_resource(
                    endpoint,
                    should_use_incremental_field,
                    incremental_field,
                    db_incremental_field_last_value,
                )
            ],
        }
        resource = rest_api_resource(config, team_id, job_id, db_incremental_field_last_value)
        items = lambda: resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=cfg.primary_keys,
        partition_keys=[cfg.partition_key],
        partition_mode=cfg.partition_mode,
        partition_format=cfg.partition_format,
        partition_count=cfg.partition_count,
        partition_size=cfg.partition_size,
        sort_mode=cfg.sort_mode,
    )
