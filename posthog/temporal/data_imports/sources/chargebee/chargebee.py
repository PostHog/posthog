import base64
from typing import Any, Optional

import requests
from requests import Request, Response

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource


def incremental_param(cursor_path: str) -> dict[str, Any]:
    return {
        "type": "incremental",
        "cursor_path": cursor_path,
        "initial_value": 0,
    }


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "Customers": {
            "name": "Customers",
            "table_name": "customers",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "list[*].customer",
                "path": "/v2/customers",
                "params": {
                    # the parameters below can optionally be configured
                    "updated_at[after]": incremental_param("updated_at") if should_use_incremental_field else None,
                    "limit": 100,
                    # by default, API does not return deleted resources
                    "include_deleted": "true",
                },
            },
            "table_format": "delta",
        },
        # Note: it is possible to filter by event type, but for now we're
        # fetching all events
        "Events": {
            "name": "Events",
            "table_name": "events",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "list[*].event",
                "path": "/v2/events",
                "params": {
                    # the parameters below can optionally be configured
                    "occurred_at[after]": incremental_param("occurred_at") if should_use_incremental_field else None,
                    "limit": 100,
                },
            },
            "table_format": "delta",
        },
        "Invoices": {
            "name": "Invoices",
            "table_name": "invoices",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "list[*].invoice",
                "path": "/v2/invoices",
                "params": {
                    # the parameters below can optionally be configured
                    "updated_at[after]": incremental_param("updated_at") if should_use_incremental_field else None,
                    "limit": 100,
                    # by default, API does not return deleted resources
                    "include_deleted": "true",
                },
            },
            "table_format": "delta",
        },
        "Orders": {
            "name": "Orders",
            "table_name": "orders",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "list[*].order",
                "path": "/v2/orders",
                "params": {
                    # the parameters below can optionally be configured
                    "updated_at[after]": incremental_param("updated_at") if should_use_incremental_field else None,
                    "limit": 100,
                    # by default, API does not return deleted resources
                    "include_deleted": "true",
                },
            },
            "table_format": "delta",
        },
        "Subscriptions": {
            "name": "Subscriptions",
            "table_name": "subscriptions",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "list[*].subscription",
                "path": "/v2/subscriptions",
                "params": {
                    # the parameters below can optionally be configured
                    "updated_at[after]": incremental_param("updated_at") if should_use_incremental_field else None,
                    "limit": 100,
                    # by default, API does not return deleted resources
                    "include_deleted": "true",
                },
            },
            "table_format": "delta",
        },
        "Transactions": {
            "name": "Transactions",
            "table_name": "transactions",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "list[*].transaction",
                "path": "/v2/transactions",
                "params": {
                    # the parameters below can optionally be configured
                    "updated_at[after]": incremental_param("updated_at") if should_use_incremental_field else None,
                    "limit": 100,
                    # by default, API does not return deleted resources
                    "include_deleted": "true",
                },
            },
            "table_format": "delta",
        },
    }
    return resources[name]


class ChargebeePaginator(BasePaginator):
    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        self._next_offset = None

        if not res:
            self._has_next_page = False
            return

        if "next_offset" in res:
            self._has_next_page = True
            self._next_offset = res["next_offset"]
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}

        request.params["offset"] = self._next_offset


def chargebee_source(
    api_key: str,
    site_name: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": f"https://{site_name}.chargebee.com/api",
            "auth": {
                "type": "http_basic",
                "username": api_key,
                "password": "",
            },
            "paginator": ChargebeePaginator(),
        },
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    return rest_api_resource(config, team_id, job_id, db_incremental_field_last_value)


def validate_credentials(api_key: str, site_name: str) -> bool:
    basic_token = base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")
    res = requests.get(
        f"https://{site_name}.chargebee.com/api/v2/customers?limit=1",
        headers={"Authorization": f"Basic {basic_token}"},
    )
    return res.status_code == 200
