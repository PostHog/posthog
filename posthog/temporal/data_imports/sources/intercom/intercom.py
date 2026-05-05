from typing import Any, Optional

from requests import Request, Response

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
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


def _default_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Intercom-Version": INTERCOM_API_VERSION,
    }


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
        if not incremental_field:
            raise ValueError(f"Intercom search endpoint {name!r} requires an incremental_field")
        endpoint["json"] = _build_search_body(cfg, incremental_field, db_incremental_field_last_value)
    elif cfg.method == "POST" and cfg.paginator_kind in ("cursor", "next_url"):
        # POST list endpoints (`/companies/list`) take `per_page` in the body.
        # The next-URL paginator preserves the POST method and body when it
        # follows `pages.next`, so the body just needs to be set once.
        endpoint["json"] = {"per_page": cfg.page_size}
    elif cfg.paginator_kind in ("cursor", "next_url"):
        endpoint["params"] = {"per_page": cfg.page_size}

    # Upsert on incremental search syncs so updates to existing rows replace
    # the prior version instead of appending duplicates. Non-incremental
    # endpoints stay on full-refresh replace.
    write_disposition: Any = (
        {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field and cfg.paginator_kind == "search"
        else "replace"
    )

    return {
        "name": cfg.name,
        "table_name": cfg.name,
        "write_disposition": write_disposition,
        "endpoint": endpoint,
        "table_format": "delta",
    }


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
        response = make_tracked_session().get(
            f"{INTERCOM_API_BASE}/me",
            headers={
                "Authorization": f"Bearer {access_token}",
                **_default_headers(),
            },
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

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[cfg.primary_key],
        partition_keys=[cfg.partition_key],
        partition_mode=cfg.partition_mode,
        partition_format=cfg.partition_format,
        partition_count=cfg.partition_count,
        partition_size=cfg.partition_size,
        sort_mode="asc",
    )
