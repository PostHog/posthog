from typing import Any

import dlt
import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource


def get_resource(
    name: str, should_use_incremental_field: bool, db_incremental_field_last_value: Any = None
) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "Campaigns": {
            "name": "Campaigns",
            "table_name": "campaigns",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "data",
                "path": "/campaigns",
                "params": {
                    "page[size]": 100,
                    "filter": f"greater-than(updated_at,{db_incremental_field_last_value})"
                    if should_use_incremental_field and db_incremental_field_last_value
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Events": {
            "name": "Events",
            "table_name": "events",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "data",
                "path": "/events",
                "params": {
                    "page[size]": 100,
                    "filter": f"greater-than(datetime,{db_incremental_field_last_value})"
                    if should_use_incremental_field and db_incremental_field_last_value
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Flows": {
            "name": "Flows",
            "table_name": "flows",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "data",
                "path": "/flows",
                "params": {
                    "page[size]": 50,  # Flows endpoint max is 50
                    "filter": f"greater-than(updated,{db_incremental_field_last_value})"
                    if should_use_incremental_field and db_incremental_field_last_value
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Lists": {
            "name": "Lists",
            "table_name": "lists",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "data",
                "path": "/lists",
                "params": {
                    "filter": f"greater-than(updated,{db_incremental_field_last_value})"
                    if should_use_incremental_field and db_incremental_field_last_value
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Metrics": {
            "name": "Metrics",
            "table_name": "metrics",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "data",
                "path": "/metrics",
                "params": {
                    "page[size]": 100,
                },
            },
            "table_format": "delta",
        },
        "Profiles": {
            "name": "Profiles",
            "table_name": "profiles",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "data",
                "path": "/profiles",
                "params": {
                    "page[size]": 100,
                    "filter": f"greater-than(updated,{db_incremental_field_last_value})"
                    if should_use_incremental_field and db_incremental_field_last_value
                    else None,
                },
            },
            "table_format": "delta",
        },
    }
    return resources[name]


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
            request.url = self._next_offset


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


@dlt.source(max_table_nesting=0)
def klaviyo_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
):
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
            )
        ],
    }

    yield from rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)
