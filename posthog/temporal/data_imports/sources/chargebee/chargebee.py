import base64
import dataclasses
from typing import Any, Optional

import requests
from requests import Request, Response

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@dataclasses.dataclass
class ChargebeeResumeConfig:
    next_offset: str


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
    def __init__(self) -> None:
        super().__init__()
        self._next_offset: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume offset on the first request.
        if self._next_offset is not None:
            if request.params is None:
                request.params = {}
            request.params["offset"] = self._next_offset

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

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._next_offset is not None and self._has_next_page:
            return {"next_offset": self._next_offset}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_offset = state.get("next_offset")
        if next_offset is not None:
            self._next_offset = str(next_offset)
            self._has_next_page = True


def chargebee_source(
    api_key: str,
    site_name: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ChargebeeResumeConfig],
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

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"next_offset": resume_config.next_offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL
        # handles cleanup on completion.
        if state and state.get("next_offset"):
            resumable_source_manager.save_state(ChargebeeResumeConfig(next_offset=str(state["next_offset"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(api_key: str, site_name: str) -> bool:
    basic_token = base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")
    res = requests.get(
        f"https://{site_name}.chargebee.com/api/v2/customers?limit=1",
        headers={"Authorization": f"Basic {basic_token}"},
    )
    return res.status_code == 200
