from typing import Any

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import Endpoint, EndpointResource
from posthog.temporal.data_imports.sources.intercom.settings import INTERCOM_ENDPOINTS

INTERCOM_BASE_URL = "https://api.intercom.io"
INTERCOM_VERSION = "2.11"


class IntercomCursorPaginator(BasePaginator):
    """Paginator for Intercom GET endpoints using cursor-based pagination.

    Reads cursor from `pages.next.starting_after` in the response and sets it
    as a `starting_after` query parameter on subsequent requests.
    """

    def __init__(self, per_page: int = 150):
        super().__init__()
        self._per_page = per_page
        self._next_cursor: str | None = None

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["per_page"] = self._per_page

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        try:
            response_data = response.json()
            pages = response_data.get("pages", {})
            next_page = pages.get("next", {})
            self._next_cursor = next_page.get("starting_after") if isinstance(next_page, dict) else None
            self._has_next_page = self._next_cursor is not None
        except Exception:
            self._has_next_page = False
            self._next_cursor = None

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["per_page"] = self._per_page
        if self._next_cursor:
            request.params["starting_after"] = self._next_cursor


class IntercomBodyCursorPaginator(BasePaginator):
    """Paginator for Intercom POST endpoints (e.g. /companies/list) using cursor-based pagination.

    Same cursor logic as IntercomCursorPaginator but passes the cursor
    in the JSON request body instead of query parameters.
    """

    def __init__(self, per_page: int = 150):
        super().__init__()
        self._per_page = per_page
        self._next_cursor: str | None = None

    def init_request(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        request.json["per_page"] = self._per_page

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        try:
            response_data = response.json()
            pages = response_data.get("pages", {})
            next_page = pages.get("next", {})
            self._next_cursor = next_page.get("starting_after") if isinstance(next_page, dict) else None
            self._has_next_page = self._next_cursor is not None
        except Exception:
            self._has_next_page = False
            self._next_cursor = None

    def update_request(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        request.json["per_page"] = self._per_page
        if self._next_cursor:
            request.json["pagination"] = {"starting_after": self._next_cursor}


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    config = INTERCOM_ENDPOINTS[name]

    endpoint_config: Endpoint = {
        "path": config.path,
        "data_selector": config.data_selector,
    }

    if not config.paginated:
        endpoint_config["paginator"] = "single_page"
    elif config.method == "POST":
        endpoint_config["method"] = "POST"
        endpoint_config["paginator"] = IntercomBodyCursorPaginator(per_page=config.page_size)
    else:
        endpoint_config["paginator"] = IntercomCursorPaginator(per_page=config.page_size)

    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_key,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    try:
        res = requests.get(
            f"{INTERCOM_BASE_URL}/admins",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Intercom-Version": INTERCOM_VERSION,
            },
            timeout=10,
        )
        if res.status_code == 200:
            return True, None

        return False, f"HTTP {res.status_code}: {res.text}"
    except Exception as e:
        return False, str(e)


def intercom_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any | None = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = INTERCOM_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": INTERCOM_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Intercom-Version": INTERCOM_VERSION,
            },
        },
        "resource_defaults": {
            "primary_key": "id",
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    resources = rest_api_resources(config, team_id, job_id, None)
    assert len(resources) == 1
    resource = resources[0]

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[endpoint_config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.paginated else None,
        partition_format="week" if endpoint_config.paginated else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.paginated else None,
        sort_mode="asc" if endpoint_config.paginated else None,
    )
