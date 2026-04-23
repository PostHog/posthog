import base64
import dataclasses
from typing import Any, Optional

import requests
from requests import Request, Response

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator, JSONLinkPaginator
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager

from products.data_warehouse.backend.models.external_table_definitions import get_dlt_mapping_for_external_table


@dataclasses.dataclass
class ZendeskResumeConfig:
    """Resume state for Zendesk endpoints.

    Two pagination contracts are in play:
    - URL-based: the standard endpoints (``JSONLinkPaginator`` on ``links.next``)
      and the incremental ``ticket_events`` / ``ticket_metric_events``
      endpoints both advance via a full next-page URL — persisted as
      ``next_url``.
    - Cursor-based: the incremental ``tickets`` endpoint advances via a
      ``start_time`` cursor (``generated_timestamp`` of the last ticket) —
      persisted as ``next_start_time``.

    Exactly one of the two fields is set for a given checkpoint; the loader
    picks the shape matching the endpoint's paginator.
    """

    next_url: Optional[str] = None
    next_start_time: Optional[int] = None


class ResumableJSONLinkPaginator(JSONLinkPaginator):
    """``JSONLinkPaginator`` with resume support.

    When seeded via ``set_resume_state`` the paginator redirects the *initial*
    request to the saved next URL, so resumed runs skip the already-consumed
    pages instead of replaying from the first page.
    """

    def init_request(self, request: Request) -> None:
        if self._next_url is not None:
            request.url = self._next_url

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._next_url and self._has_next_page:
            return {"next_url": self._next_url}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_url = state.get("next_url")
        if next_url:
            self._next_url = next_url
            self._has_next_page = True


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "brands": {
            "name": "brands",
            "table_name": "brands",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_brands"),
            "endpoint": {
                "data_selector": "brands",
                "path": "/api/v2/brands",
                "paginator": ResumableJSONLinkPaginator(next_url_path="links.next"),
                "params": {
                    "page[size]": 100,
                },
            },
            "table_format": "delta",
        },
        "organizations": {
            "name": "organizations",
            "table_name": "organizations",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_organizations"),
            "endpoint": {
                "data_selector": "organizations",
                "path": "/api/v2/organizations",
                "paginator": ResumableJSONLinkPaginator(next_url_path="links.next"),
                "params": {
                    "page[size]": 100,
                },
            },
            "table_format": "delta",
        },
        "groups": {
            "name": "groups",
            "table_name": "groups",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_groups"),
            "endpoint": {
                "data_selector": "groups",
                "path": "/api/v2/groups",
                "paginator": ResumableJSONLinkPaginator(next_url_path="links.next"),
                "params": {
                    # the parameters below can optionally be configured
                    # "exclude_deleted": "OPTIONAL_CONFIG",
                    "page[size]": 100,
                },
            },
            "table_format": "delta",
        },
        "sla_policies": {
            "name": "sla_policies",
            "table_name": "sla_policies",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_sla_policies"),
            "endpoint": {
                "data_selector": "sla_policies",
                "path": "/api/v2/slas/policies",
                "paginator": ResumableJSONLinkPaginator(next_url_path="links.next"),
            },
            "table_format": "delta",
        },
        "users": {
            "name": "users",
            "table_name": "users",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_users"),
            "endpoint": {
                "data_selector": "users",
                "path": "/api/v2/users",
                "paginator": ResumableJSONLinkPaginator(next_url_path="links.next"),
                "params": {
                    # the parameters below can optionally be configured
                    # "role": "OPTIONAL_CONFIG",
                    # "role[]": "OPTIONAL_CONFIG",
                    # "permission_set": "OPTIONAL_CONFIG",
                    # "external_id": "OPTIONAL_CONFIG",
                    "page[size]": 100,
                },
            },
            "table_format": "delta",
        },
        "ticket_fields": {
            "name": "ticket_fields",
            "table_name": "ticket_fields",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_ticket_fields"),
            "endpoint": {
                "data_selector": "ticket_fields",
                "path": "/api/v2/ticket_fields",
                "paginator": ResumableJSONLinkPaginator(next_url_path="links.next"),
                "params": {
                    # the parameters below can optionally be configured
                    # "locale": "OPTIONAL_CONFIG",
                    # "creator": "OPTIONAL_CONFIG",
                    "page[size]": 100,
                },
            },
            "table_format": "delta",
        },
        "ticket_events": {
            "name": "ticket_events",
            "table_name": "ticket_events",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_ticket_events"),
            "endpoint": {
                "data_selector": "ticket_events",
                "path": "/api/v2/incremental/ticket_events?start_time=0",
                "paginator": ZendeskIncrementalEndpointPaginator(),
                "params": {
                    "per_page": 1000,
                    # Having to use `start_time` in the initial path until incrementality works
                    # "start_time": 0,
                    # Incrementality is disabled as we can't access end_time on the root object
                    # "start_time": {
                    #     "type": "incremental",
                    #     "cursor_path": "end_time",
                    #     "initial_value": 0,
                    # },
                },
            },
            "table_format": "delta",
        },
        "tickets": {
            "name": "tickets",
            "table_name": "tickets",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_tickets"),
            "endpoint": {
                "data_selector": "tickets",
                "path": "/api/v2/incremental/tickets",
                "paginator": ZendeskTicketsIncrementalEndpointPaginator(),
                "params": {
                    "per_page": 1000,
                    "start_time": {
                        "type": "incremental",
                        "cursor_path": "generated_timestamp",
                        "initial_value": 0,
                    },
                },
            },
            "table_format": "delta",
        },
        "ticket_metric_events": {
            "name": "ticket_metric_events",
            "table_name": "ticket_metric_events",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("zendesk_ticket_metric_events"),
            "endpoint": {
                "data_selector": "ticket_metric_events",
                "path": "/api/v2/incremental/ticket_metric_events?start_time=0",
                "paginator": ZendeskIncrementalEndpointPaginator(),
                "params": {
                    "per_page": 1000,
                    # Having to use `start_time` in the initial path until incrementality works
                    # "start_time": 0,
                    # Incrementality is disabled as we can't access end_time on the root object
                    # "start_time": {
                    #     "type": "incremental",
                    #     "cursor_path": "end_time",
                    #     "initial_value": 0,
                    # },
                },
            },
            "table_format": "delta",
        },
    }

    return resources[name]


class ZendeskTicketsIncrementalEndpointPaginator(BasePaginator):
    def __init__(self) -> None:
        super().__init__()
        self._next_start_time: Optional[int] = None

    def init_request(self, request: Request) -> None:
        # When seeded via ``set_resume_state`` the saved cursor must override
        # the incremental ``start_time`` the rest framework injected, so the
        # first request lands on the resume page instead of the initial one.
        if self._next_start_time is not None:
            if request.params is None:
                request.params = {}
            request.params["start_time"] = self._next_start_time

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        self._next_start_time = None

        if not res:
            self._has_next_page = False
            return

        if not res["end_of_stream"]:
            self._has_next_page = True

            last_value_in_response = res["tickets"][-1]["generated_timestamp"]
            self._next_start_time = last_value_in_response
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}

        request.params["start_time"] = self._next_start_time

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._next_start_time is not None and self._has_next_page:
            return {"next_start_time": self._next_start_time}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_start_time = state.get("next_start_time")
        if next_start_time is not None:
            self._next_start_time = int(next_start_time)
            self._has_next_page = True


class ZendeskIncrementalEndpointPaginator(BasePaginator):
    def __init__(self) -> None:
        super().__init__()
        self._next_page: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # When seeded via ``set_resume_state`` the saved URL is the full next
        # page URL; sending the first request to it skips the hardcoded
        # ``start_time=0`` path used on a fresh run.
        if self._next_page is not None:
            request.url = self._next_page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        self._next_page = None

        if not res:
            self._has_next_page = False
            return

        if not res["end_of_stream"]:
            self._has_next_page = True

            self._next_page = res["next_page"]
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        request.url = self._next_page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._next_page and self._has_next_page:
            return {"next_url": self._next_page}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_url = state.get("next_url")
        if next_url:
            self._next_page = next_url
            self._has_next_page = True


def _endpoint_uses_start_time_cursor(endpoint: str) -> bool:
    """Only the ``tickets`` endpoint persists a ``start_time`` cursor; every
    other endpoint persists a ``next_url``."""
    return endpoint == "tickets"


def zendesk_source(
    subdomain: str,
    api_key: str,
    email_address: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    resumable_source_manager: ResumableSourceManager[ZendeskResumeConfig],
    should_use_incremental_field: bool = False,
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": f"https://{subdomain}.zendesk.com/",
            "auth": {
                "type": "http_basic",
                "username": f"{email_address}/token",
                "password": api_key,
            },
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

    uses_start_time_cursor = _endpoint_uses_start_time_cursor(endpoint)

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            if uses_start_time_cursor and resume_config.next_start_time is not None:
                initial_paginator_state = {"next_start_time": resume_config.next_start_time}
            elif not uses_start_time_cursor and resume_config.next_url:
                initial_paginator_state = {"next_url": resume_config.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to — Redis TTL
        # handles cleanup on completion. Matches klaviyo / reddit_ads.
        if not state:
            return
        if uses_start_time_cursor:
            next_start_time = state.get("next_start_time")
            if next_start_time is not None:
                resumable_source_manager.save_state(ZendeskResumeConfig(next_start_time=int(next_start_time)))
        else:
            next_url = state.get("next_url")
            if next_url:
                resumable_source_manager.save_state(ZendeskResumeConfig(next_url=next_url))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(subdomain: str, api_key: str, email_address: str) -> bool:
    basic_token = base64.b64encode(f"{email_address}/token:{api_key}".encode("ascii")).decode("ascii")
    res = requests.get(
        f"https://{subdomain}.zendesk.com/api/v2/tickets/count",
        headers={"Authorization": f"Basic {basic_token}"},
    )

    return res.status_code == 200
