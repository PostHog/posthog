import logging
from typing import Any

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import Endpoint, EndpointResource
from posthog.temporal.data_imports.sources.intercom.settings import INTERCOM_ENDPOINTS

logger = logging.getLogger(__name__)

INTERCOM_BASE_URL = "https://api.intercom.io"
INTERCOM_VERSION = "2.11"


class IntercomCursorPaginator(BasePaginator):
    """Paginator for Intercom endpoints using cursor-based pagination.

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


class IntercomSearchPaginator(BasePaginator):
    """Paginator for Intercom search endpoints (POST /contacts/search, etc.).

    Search endpoints use cursor-based pagination within the JSON request body,
    not query parameters.
    """

    def __init__(self, per_page: int = 150):
        super().__init__()
        self._per_page = per_page
        self._next_cursor: str | None = None

    def init_request(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        if "pagination" not in request.json:
            request.json["pagination"] = {}
        request.json["pagination"]["per_page"] = self._per_page

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
        if "pagination" not in request.json:
            request.json["pagination"] = {}
        request.json["pagination"]["per_page"] = self._per_page
        if self._next_cursor:
            request.json["pagination"]["starting_after"] = self._next_cursor


class IntercomPageNumberPaginator(BasePaginator):
    """Paginator for Intercom POST endpoints that use page-number pagination
    via query parameters (e.g. POST /companies/list?page=1&per_page=15).
    """

    def __init__(self, per_page: int = 50):
        super().__init__()
        self._per_page = per_page
        self._current_page = 1
        self._total_pages = 1

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self._current_page
        request.params["per_page"] = self._per_page

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        try:
            response_data = response.json()
            pages = response_data.get("pages", {})
            self._total_pages = pages.get("total_pages", 1)
            self._has_next_page = self._current_page < self._total_pages
        except Exception:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._current_page += 1
        if request.params is None:
            request.params = {}
        request.params["page"] = self._current_page
        request.params["per_page"] = self._per_page


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any | None = None,
) -> EndpointResource:
    config = INTERCOM_ENDPOINTS[name]

    if should_use_incremental_field and config.search_path:
        # Use search endpoint for server-side filtering by updated_at
        filter_value = int(db_incremental_field_last_value) if db_incremental_field_last_value is not None else 0
        json_body: dict[str, Any] = {
            "query": {
                "operator": "OR",
                "value": [
                    {"field": "updated_at", "operator": ">", "value": filter_value},
                    {"field": "updated_at", "operator": "=", "value": filter_value},
                ],
            },
            "sort": {
                "field": "updated_at",
                "order": "ascending",
            },
        }

        endpoint_config: Endpoint = {
            "path": config.search_path,
            "method": "POST",
            "json": json_body,
            "data_selector": config.search_data_selector or config.data_selector,
            "paginator": IntercomSearchPaginator(per_page=config.page_size),
        }
    else:
        endpoint_config = {
            "path": config.path,
            "data_selector": config.data_selector,
        }

        if not config.paginated:
            endpoint_config["paginator"] = "single_page"
        elif config.method == "POST":
            endpoint_config["method"] = "POST"
            endpoint_config["paginator"] = IntercomPageNumberPaginator(per_page=config.page_size)
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

    resource_config = get_resource(endpoint, should_use_incremental_field, db_incremental_field_last_value)
    logger.info(
        "Intercom source: endpoint=%s, incremental=%s, last_value=%s, path=%s",
        endpoint,
        should_use_incremental_field,
        db_incremental_field_last_value,
        resource_config["endpoint"].get("path"),
    )

    config: RESTAPIConfig = {
        "client": {
            "base_url": INTERCOM_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {
                "Accept": "application/json",
                "Intercom-Version": INTERCOM_VERSION,
            },
        },
        "resource_defaults": {
            "primary_key": "id",
            "write_disposition": "replace",
        },
        "resources": [resource_config],
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
