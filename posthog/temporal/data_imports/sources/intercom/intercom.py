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


def _build_paginator(cfg: IntercomEndpointConfig) -> BasePaginator:
    if cfg.paginator_kind == "cursor":
        return JSONResponseCursorPaginator(
            cursor_path="pages.next.starting_after",
            cursor_param="starting_after",
        )
    if cfg.paginator_kind == "next_url":
        return JSONResponsePaginator(next_url_path="pages.next")
    return SinglePagePaginator()


def get_resource(name: str) -> EndpointResource:
    cfg = INTERCOM_ENDPOINTS[name]

    endpoint: Endpoint = {
        "path": cfg.path,
        "data_selector": cfg.data_selector,
        "paginator": _build_paginator(cfg),
    }

    if cfg.paginator_kind in ("cursor", "next_url"):
        endpoint["params"] = {"per_page": cfg.page_size}

    return {
        "name": cfg.name,
        "table_name": cfg.name,
        "write_disposition": "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    """Validate an Intercom access token by hitting `/me`.

    Works identically with OAuth-issued access tokens and Personal Access
    Tokens — both flow as `Authorization: Bearer …`.
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
        return False, "Your Intercom access token is missing required scopes. Please reconnect."
    return False, f"HTTP {response.status_code}: {response.text[:200]}"


def intercom_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
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
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    resource = rest_api_resource(config, team_id, job_id, None)

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
