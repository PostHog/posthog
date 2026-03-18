from typing import Any, Optional

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import Endpoint, EndpointResource
from posthog.temporal.data_imports.sources.intercom.settings import INTERCOM_ENDPOINTS, PARTITION_FIELDS

INTERCOM_BASE_URL = "https://api.intercom.io"
INTERCOM_API_VERSION = "2.11"


def _base_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Intercom-Version": INTERCOM_API_VERSION,
    }


class IntercomCursorPaginator(BasePaginator):
    """Paginator for Intercom API using cursor-based pagination via pages.next.starting_after."""

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        if not res:
            self._has_next_page = False
            return

        pages = res.get("pages", {})
        next_page = pages.get("next")

        if next_page and next_page.get("starting_after"):
            self._starting_after = next_page["starting_after"]
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._has_next_page:
            if request.params is None:
                request.params = {}
            request.params["starting_after"] = self._starting_after


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    config = INTERCOM_ENDPOINTS[name]

    endpoint_config: Endpoint = {
        "path": config.path,
        "data_selector": config.data_selector,
        "params": {
            "per_page": config.page_size,
        },
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": "id",
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _iter_companies(api_key: str, page_size: int = 50) -> Any:
    """Custom iterator for companies endpoint which uses POST with JSON body pagination."""
    url = f"{INTERCOM_BASE_URL}/companies/list"
    headers = {
        **_base_headers(),
        "Authorization": f"Bearer {api_key}",
    }

    body: dict[str, Any] = {"per_page": page_size}

    while True:
        response = requests.post(url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        data = response.json()

        yield from data.get("data", [])

        pages = data.get("pages", {})
        next_page = pages.get("next")
        if next_page and next_page.get("starting_after"):
            body["starting_after"] = next_page["starting_after"]
        else:
            break


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Validate Intercom API credentials by calling GET /me."""
    url = f"{INTERCOM_BASE_URL}/me"
    headers = {
        **_base_headers(),
        "Authorization": f"Bearer {api_key}",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            return True, None

        try:
            error_data = response.json()
            errors = error_data.get("errors", [])
            if errors:
                return False, errors[0].get("message", response.text)
        except Exception:
            pass

        return False, response.text
    except requests.exceptions.RequestException as e:
        return False, str(e)


def intercom_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = INTERCOM_ENDPOINTS[endpoint]
    partition_key = PARTITION_FIELDS.get(endpoint)

    # Companies use POST body pagination — handled with a custom iterator
    if endpoint_config.uses_post_pagination:
        return SourceResponse(
            name=endpoint,
            items=lambda: _iter_companies(api_key, page_size=endpoint_config.page_size),
            primary_keys=["id"],
            partition_count=1 if partition_key else None,
            partition_size=1 if partition_key else None,
            partition_mode="datetime" if partition_key else None,
            partition_format="week" if partition_key else None,
            partition_keys=[partition_key] if partition_key else None,
        )

    config: RESTAPIConfig = {
        "client": {
            "base_url": INTERCOM_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": _base_headers(),
            "paginator": IntercomCursorPaginator() if endpoint_config.supports_pagination else None,
        },
        "resource_defaults": {
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    resources = rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)
    assert len(resources) == 1
    resource = resources[0]

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1 if partition_key else None,
        partition_size=1 if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="week" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )
