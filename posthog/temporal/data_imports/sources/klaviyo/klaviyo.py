from datetime import date, datetime
from typing import Any, Optional

import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.sources.klaviyo.settings import KLAVIYO_ENDPOINTS, KlaviyoEndpointConfig


def _format_incremental_value(value: Any) -> str:
    """Format incremental field value as ISO string for Klaviyo API filters."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).isoformat()
    return str(value)


def _build_filter(
    config: KlaviyoEndpointConfig,
    incremental_field: str | None,
    formatted_value: str | None,
) -> str | None:
    """Build Klaviyo filter string from config."""
    filter_field = incremental_field or config.default_incremental_field
    incremental_filter = f"greater-than({filter_field},{formatted_value})" if formatted_value else None

    if config.base_filter and incremental_filter:
        return f"and({config.base_filter},{incremental_filter})"
    elif config.base_filter:
        return config.base_filter
    else:
        return incremental_filter


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> EndpointResource:
    config = KLAVIYO_ENDPOINTS[name]

    formatted_last_value = (
        _format_incremental_value(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value
        else None
    )

    filter_value = _build_filter(config, incremental_field, formatted_last_value)

    params: dict[str, Any] = {}
    if config.page_size is not None and config.page_size > 0:
        params["page[size]"] = config.page_size
    if filter_value:
        params["filter"] = filter_value
    if config.sort:
        params["sort"] = config.sort

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
            "data_selector": "data",
            "path": config.path,
            "params": params if params else {},
        },
        "table_format": "delta",
    }


class KlaviyoPaginator(BasePaginator):
    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        res = response.json()

        self._next_offset = None

        if not res:
            self._has_next_page = False
            return

        links = res.get("links", {})
        next_url = links.get("next")

        if next_url:
            self._next_offset = next_url
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._next_offset:
            # Use the full next URL from the response
            # Clear params since the next URL already contains all query parameters
            request.url = self._next_offset
            request.params = {}


def validate_credentials(api_key: str) -> bool:
    url = "https://a.klaviyo.com/api/accounts"
    headers = {
        "Authorization": f"Klaviyo-API-Key {api_key}",
        "revision": "2024-10-15",
        "Accept": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten the 'attributes' object into the root level for a single item."""
    if "attributes" in item and isinstance(item["attributes"], dict):
        attributes = item.pop("attributes")
        item.update(attributes)
    return item


def klaviyo_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = KLAVIYO_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": "https://a.klaviyo.com/api",
            "auth": {
                "type": "api_key",
                "api_key": f"Klaviyo-API-Key {api_key}",
                "name": "Authorization",
                "location": "header",
            },
            "headers": {
                "revision": "2024-10-15",
                "Accept": "application/json",
            },
            "paginator": KlaviyoPaginator(),
        },
        "resource_defaults": {
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "params": {
                    "page[size]": 100,
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
    resource = resources[0].add_map(_flatten_item)

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
