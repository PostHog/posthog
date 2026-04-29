import dataclasses
from typing import Any, Optional

import requests
from requests import Request, Response

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.clerk.settings import CLERK_ENDPOINTS
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from posthog.temporal.data_imports.sources.common.rest_source.typing import Endpoint, EndpointResource
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@dataclasses.dataclass
class ClerkResumeConfig:
    """Resume state for Clerk endpoints.

    All Clerk endpoints use offset-based pagination, so the checkpoint is just
    the next offset to fetch. On resume we start fetching from the saved offset
    (at-least-once semantics): any duplicates from a batch that was yielded but
    whose checkpoint did not persist are deduped by the ``id`` primary key.
    """

    offset: int


def get_resource(name: str) -> EndpointResource:
    config = CLERK_ENDPOINTS[name]

    params: dict[str, Any] = {
        "limit": config.page_size,
    }

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
    }

    # Only set data_selector for endpoints that return wrapped responses {data: [...], total_count: ...}
    if config.is_wrapped_response:
        endpoint_config["data_selector"] = "data"

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


class ClerkPaginator(BasePaginator):
    """Paginator for Clerk API using offset-based pagination."""

    def __init__(self, limit: int = 100) -> None:
        super().__init__()
        self._limit = limit
        self._offset = 0

    def init_request(self, request: Request) -> None:
        # Emit the seeded offset on the first request so resume starts from the
        # saved page. Fresh runs (offset=0) omit the param to preserve the
        # existing URL shape.
        if self._offset > 0:
            if request.params is None:
                request.params = {}
            request.params["offset"] = self._offset

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        res = response.json()

        if not res:
            self._has_next_page = False
            return

        # Clerk endpoints return either:
        # - Direct array: /users, /invitations
        # - Wrapped object {data: [...], total_count: ...}: /organizations, /organization_memberships
        total_count: Optional[int] = None
        if isinstance(res, dict) and "data" in res:
            items = res["data"]
            raw_total = res.get("total_count")
            if isinstance(raw_total, int):
                total_count = raw_total
        elif isinstance(res, list):
            items = res
        else:
            items = []

        next_offset = self._offset + len(items)

        # Prefer total_count for wrapped endpoints so we don't issue an extra
        # empty request when total_count is exactly divisible by limit.
        if total_count is not None:
            self._has_next_page = next_offset < total_count
        else:
            self._has_next_page = len(items) >= self._limit

        if self._has_next_page:
            self._offset = next_offset

    def update_request(self, request: Request) -> None:
        if self._has_next_page:
            if request.params is None:
                request.params = {}
            request.params["offset"] = self._offset

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # rest_client only calls this when has_next_page is True, so ``_offset``
        # already points at the page we still need to fetch.
        return {"offset": self._offset}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self._offset = int(offset)
            self._has_next_page = True


# Timestamp fields that need conversion from milliseconds to seconds
TIMESTAMP_FIELDS = [
    "created_at",
    "updated_at",
    "last_sign_in_at",
    "last_active_at",
    "mfa_enabled_at",
    "mfa_disabled_at",
    "password_last_updated_at",
    "legal_accepted_at",
    "expires_at",  # invitations
]


def _convert_timestamps(item: dict[str, Any]) -> dict[str, Any]:
    """Convert Clerk timestamp fields from milliseconds to seconds."""
    for field in TIMESTAMP_FIELDS:
        if field in item and item[field] is not None:
            # Clerk returns timestamps in milliseconds, convert to seconds
            # Use integer division to maintain int64 type for delta table compatibility
            item[field] = item[field] // 1000
    return item


def validate_credentials(secret_key: str) -> tuple[bool, str | None]:
    """Validate Clerk API credentials by making a test request."""
    url = "https://api.clerk.com/v1/users"
    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, params={"limit": 1}, timeout=10)

        if response.status_code == 200:
            return True, None

        try:
            error_data = response.json()
            if error_data.get("errors"):
                return False, error_data["errors"][0].get("message", response.text)
        except Exception:
            pass

        return False, response.text
    except requests.exceptions.RequestException as e:
        return False, str(e)


def clerk_source(
    secret_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ClerkResumeConfig],
) -> SourceResponse:
    endpoint_config = CLERK_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": "https://api.clerk.com/v1",
            "auth": {
                "type": "bearer",
                "token": secret_key,
            },
            "headers": {
                "Content-Type": "application/json",
            },
            "paginator": ClerkPaginator(limit=endpoint_config.page_size),
        },
        "resource_defaults": {
            "write_disposition": "replace",
            "endpoint": {
                "params": {
                    "limit": endpoint_config.page_size,
                },
            },
        },
        "resources": [get_resource(endpoint)],
    }

    # Seed the paginator from the saved checkpoint when resuming.
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.offset > 0:
            initial_paginator_state = {"offset": resume_config.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # rest_client passes None once the paginator is exhausted; nothing to persist then.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(ClerkResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    ).add_map(_convert_timestamps)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[endpoint_config.partition_key],
    )
