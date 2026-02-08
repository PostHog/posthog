from datetime import date, datetime
from typing import Any, Optional

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.sources.polar.settings import POLAR_ENDPOINTS


def _format_incremental_value(value: Any) -> str:
    """Format incremental field value as ISO string for Polar API filters."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).isoformat()
    return str(value)


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> EndpointResource:
    config = POLAR_ENDPOINTS[name]

    params: dict[str, Any] = {}
    if config.page_size is not None and config.page_size > 0:
        params["limit"] = config.page_size
    if config.sort:
        params["sorting"] = [config.sort]

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
        "endpoint": {
            "data_selector": "items",
            "path": config.path,
            "params": params if params else {},
        },
        "table_format": "delta",
    }


class PolarPaginator(BasePaginator):
    """Paginator for Polar API using page-based pagination."""

    def __init__(self) -> None:
        super().__init__()
        self._current_page = 1
        self._max_page: int | None = None

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        res = response.json()

        if not res:
            self._has_next_page = False
            return

        pagination = res.get("pagination", {})
        self._max_page = pagination.get("max_page", 1)

        if self._current_page < (self._max_page or 1):
            self._current_page += 1
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self._current_page


def validate_credentials(api_key: str) -> bool:
    """Validate Polar API credentials by fetching customers with limit=1."""
    url = "https://api.polar.sh/v1/customers/"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    params = {"limit": 1}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def polar_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = POLAR_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": "https://api.polar.sh/v1",
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {
                "Accept": "application/json",
            },
            "paginator": PolarPaginator(),
        },
        "resource_defaults": {
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "params": {
                    "limit": 100,
                },
            },
        },
        "resources": [
            get_resource(
                endpoint,
                should_use_incremental_field,
                db_incremental_field_last_value,
                incremental_field,
            )
        ],
    }

    resources = rest_api_resources(config, team_id, job_id, None)
    assert len(resources) == 1
    resource = resources[0]

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
