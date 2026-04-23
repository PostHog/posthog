import dataclasses
from typing import Any, Optional

import requests
from requests import Request, Response

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.attio.settings import ATTIO_ENDPOINTS
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from posthog.temporal.data_imports.sources.common.rest_source.typing import Endpoint, EndpointResource
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@dataclasses.dataclass
class AttioResumeConfig:
    """Resume state for Attio endpoints.

    Every Attio endpoint paginates by offset/limit (via ``AttioOffsetPaginator``),
    so the checkpoint is the offset of the next page to fetch. On resume the
    paginator re-enters at that offset; duplicates across restarts are deduped
    by the endpoint's ``primary_keys`` during merge.
    """

    offset: int


class AttioOffsetPaginator(BasePaginator):
    """Paginator for Attio endpoints using offset-based pagination.

    Supports both POST endpoints (pagination in JSON body) and GET endpoints (pagination in query params).
    """

    def __init__(self, limit: int = 100, use_json_body: bool = False, initial_json: Optional[dict[str, Any]] = None):
        super().__init__()
        self._limit = limit
        self._current_offset = 0
        self._next_offset: Optional[int] = 0
        self._has_next_page = False
        self._use_json_body = use_json_body
        self._initial_json = initial_json or {}

    def init_request(self, request: Request) -> None:
        if self._use_json_body:
            if request.json is None:
                request.json = dict(self._initial_json)
            else:
                for key, value in self._initial_json.items():
                    if key not in request.json:
                        request.json[key] = value
            request.json["offset"] = self._current_offset
            request.json["limit"] = self._limit
        else:
            if request.params is None:
                request.params = {}
            request.params["offset"] = self._current_offset
            request.params["limit"] = self._limit

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            response_data = response.json()
            returned_data = response_data.get("data", [])

            if len(returned_data) < self._limit:
                self._has_next_page = False
                self._next_offset = None
            else:
                self._has_next_page = True
                self._next_offset = self._current_offset + self._limit
        except Exception:
            self._has_next_page = False
            self._next_offset = None

    def update_request(self, request: Request) -> None:
        if self._next_offset is not None:
            self._current_offset = self._next_offset

        if self._use_json_body:
            if request.json is None:
                request.json = dict(self._initial_json)
            else:
                for key, value in self._initial_json.items():
                    if key not in request.json:
                        request.json[key] = value
            request.json["offset"] = self._current_offset
            request.json["limit"] = self._limit
        else:
            if request.params is None:
                request.params = {}
            request.params["offset"] = self._current_offset
            request.params["limit"] = self._limit

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # rest_client only calls this when has_next_page is True, so update_request
        # has already advanced _current_offset to the next page to fetch.
        return {"offset": self._current_offset}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self._current_offset = int(offset)
            self._next_offset = int(offset)
            self._has_next_page = True


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten the nested 'id' object into the root level."""
    if "id" in item and isinstance(item["id"], dict):
        id_obj = item.pop("id")
        for key, value in id_obj.items():
            item[key] = value
    return item


def get_resource(name: str) -> EndpointResource:
    """Build an EndpointResource from the endpoint configuration.

    Attio API doesn't support updatedAt filtering, so only full refresh is supported.
    """
    config = ATTIO_ENDPOINTS[name]

    endpoint_config: Endpoint = {
        "path": config.path,
        "data_selector": "data",
    }

    if config.method == "POST":
        endpoint_config["method"] = "POST"
        json_body: dict[str, Any] = {"sorts": [{"attribute": "created_at", "direction": "asc"}]}
        endpoint_config["json"] = json_body
        endpoint_config["paginator"] = AttioOffsetPaginator(
            limit=config.page_size, use_json_body=True, initial_json=json_body
        )
    else:
        endpoint_config["paginator"] = AttioOffsetPaginator(limit=config.page_size)

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Validate Attio API credentials by making a test request."""
    try:
        res = requests.get(
            "https://api.attio.com/v2/self",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
            timeout=10,
        )
        if res.status_code == 200:
            return True, None

        try:
            error_data = res.json()
            if error_data.get("code") == "missing_value":
                return False, "Invalid Attio API key"
        except Exception:
            pass
        return False, f"HTTP {res.status_code}: {res.text}"
    except Exception as e:
        return False, str(e)


def attio_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AttioResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    """Main source function for Attio data import.

    Attio API doesn't support updatedAt filtering, so only full refresh is supported.
    The incremental parameters are kept for interface compatibility but are not used.
    """
    endpoint_config = ATTIO_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": "https://api.attio.com",
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    # Seed the paginator when a saved checkpoint exists. A zero-offset checkpoint is
    # equivalent to a fresh run, so don't bother seeding in that case.
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.offset > 0:
            initial_paginator_state = {"offset": resume_config.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # rest_client passes None when the paginator has no next page, i.e. the
        # sync is done — leave the last checkpoint in Redis; TTL handles cleanup.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(AttioResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    ).add_map(_flatten_item)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[endpoint_config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[endpoint_config.partition_key],
        sort_mode="asc",
    )
