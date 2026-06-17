import re
import base64
from typing import Any, Optional

from requests import Request, Response

from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator, JSONLinkPaginator
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource

from products.warehouse_sources.backend.models.external_table_definitions import get_dlt_mapping_for_external_table


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
                "paginator": JSONLinkPaginator(next_url_path="links.next"),
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
                "paginator": JSONLinkPaginator(next_url_path="links.next"),
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
                "paginator": JSONLinkPaginator(next_url_path="links.next"),
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
                "paginator": JSONLinkPaginator(next_url_path="links.next"),
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
                "paginator": JSONLinkPaginator(next_url_path="links.next"),
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
                "paginator": JSONLinkPaginator(next_url_path="links.next"),
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
                # Cursor-based incremental export. The time-based export
                # (`/api/v2/incremental/tickets`) deadlocks when >1000 tickets
                # share a `generated_timestamp`: the page never advances past
                # that timestamp, so pagination loops forever re-fetching the
                # same boundary page. Cursor pagination is immune to this.
                "path": "/api/v2/incremental/tickets/cursor",
                "paginator": ZendeskTicketsCursorIncrementalPaginator(),
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


class ZendeskTicketsCursorIncrementalPaginator(BasePaginator):
    """Cursor-based pagination for Zendesk's incremental tickets export.

    The first request is seeded with `start_time` (resolved from the incremental
    cursor); every subsequent request follows the opaque `after_cursor` token.
    Unlike the time-based export, the cursor encodes the stream position rather
    than a timestamp, so it can't get pinned when many tickets share a
    `generated_timestamp`.
    """

    def __init__(self) -> None:
        super().__init__()
        self._after_cursor: Optional[str] = None

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        if not res:
            self._has_next_page = False
            return

        if "end_of_stream" not in res:
            raise ValueError("Zendesk cursor export response is missing 'end_of_stream'")

        if res["end_of_stream"]:
            self._has_next_page = False
            return

        # `end_of_stream` is False, so the stream continues and a valid, advancing
        # `after_cursor` must be present. A missing or non-advancing cursor is an
        # invalid/partial response — raise so the activity retries instead of
        # committing truncated data as a successful sync.
        after_cursor = res.get("after_cursor")
        if not after_cursor or after_cursor == self._after_cursor:
            raise ValueError("Zendesk cursor export returned end_of_stream=False without an advancing after_cursor")

        self._after_cursor = after_cursor
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}

        # After the first page we paginate purely by cursor; drop the seed
        # `start_time` so it doesn't conflict with the `cursor` param.
        request.params.pop("start_time", None)
        request.params["cursor"] = self._after_cursor


class ZendeskIncrementalEndpointPaginator(BasePaginator):
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
        # next_page is a full URL that already contains all query params —
        # clear params to avoid duplicates when prepare_request merges them.
        request.params = {}


def normalize_subdomain(subdomain: str) -> str:
    """Reduce whatever the user entered to the bare Zendesk subdomain label.

    Users frequently paste the full host ("nibbles.zendesk.com") or a URL
    ("https://nibbles.zendesk.com/") into the subdomain field. Without normalizing,
    the base URL becomes "https://nibbles.zendesk.com.zendesk.com/", whose doubled
    host the TLS handshake rejects (SSLV3_ALERT_HANDSHAKE_FAILURE) and never recovers.
    """
    subdomain = subdomain.strip()
    if "://" in subdomain:
        subdomain = subdomain.split("://", 1)[1]
    # Drop any path/query left over from a pasted URL.
    subdomain = subdomain.split("/", 1)[0]
    # Strip a trailing ".zendesk.com" so a full host collapses to the subdomain label.
    return re.sub(r"\.zendesk\.com$", "", subdomain, flags=re.IGNORECASE)


def zendesk_source(
    subdomain: str,
    api_key: str,
    email_address: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": f"https://{normalize_subdomain(subdomain)}.zendesk.com/",
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

    return rest_api_resource(config, team_id, job_id, db_incremental_field_last_value)


def validate_credentials(subdomain: str, api_key: str, email_address: str) -> bool:
    basic_token = base64.b64encode(f"{email_address}/token:{api_key}".encode("ascii")).decode("ascii")
    res = make_tracked_session().get(
        f"https://{normalize_subdomain(subdomain)}.zendesk.com/api/v2/tickets/count",
        headers={"Authorization": f"Basic {basic_token}"},
    )

    return res.status_code == 200
