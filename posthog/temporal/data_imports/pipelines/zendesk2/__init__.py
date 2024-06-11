import dlt
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from dlt.sources.helpers.requests import Response, Request
from posthog.temporal.data_imports.pipelines.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.pipelines.rest_source.typing import EndpointResource


def get_resource(name: str, is_incremental: bool) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "brands": {
            "name": "brands",
            "table_name": "brands",
            "primary_key": "id",
            "write_disposition": "merge",
            "endpoint": {
                "data_selector": "brands",
                "path": "/api/v2/brands",
                "paginator": {
                    "type": "json_response",
                    "next_url_path": "links.next",
                },
                "params": {
                    "page[size]": 100,
                },
            },
        },
        "organizations": {
            "name": "organizations",
            "table_name": "organizations",
            "primary_key": "id",
            "write_disposition": "merge",
            "endpoint": {
                "data_selector": "organizations",
                "path": "/api/v2/organizations",
                "paginator": {
                    "type": "json_response",
                    "next_url_path": "links.next",
                },
                "params": {
                    "page[size]": 100,
                },
            },
        },
        "groups": {
            "name": "groups",
            "table_name": "groups",
            "primary_key": "id",
            "write_disposition": "merge",
            "endpoint": {
                "data_selector": "groups",
                "path": "/api/v2/groups",
                "paginator": {
                    "type": "json_response",
                    "next_url_path": "links.next",
                },
                "params": {
                    # the parameters below can optionally be configured
                    # "exclude_deleted": "OPTIONAL_CONFIG",
                    "page[size]": 100,
                },
            },
        },
        "sla_policies": {
            "name": "sla_policies",
            "table_name": "sla_policies",
            "primary_key": "id",
            "write_disposition": "merge",
            "endpoint": {
                "data_selector": "sla_policies",
                "path": "/api/v2/slas/policies",
                "paginator": {
                    "type": "json_response",
                    "next_url_path": "links.next",
                },
            },
        },
        "users": {
            "name": "users",
            "table_name": "users",
            "primary_key": "id",
            "write_disposition": "merge",
            "endpoint": {
                "data_selector": "users",
                "path": "/api/v2/users",
                "paginator": {
                    "type": "json_response",
                    "next_url_path": "links.next",
                },
                "params": {
                    # the parameters below can optionally be configured
                    # "role": "OPTIONAL_CONFIG",
                    # "role[]": "OPTIONAL_CONFIG",
                    # "permission_set": "OPTIONAL_CONFIG",
                    # "external_id": "OPTIONAL_CONFIG",
                    "page[size]": 100,
                },
            },
        },
        "ticket_fields": {
            "name": "ticket_fields",
            "table_name": "ticket_fields",
            "primary_key": "id",
            "write_disposition": "merge",
            "endpoint": {
                "data_selector": "ticket_fields",
                "path": "/api/v2/ticket_fields",
                "paginator": {
                    "type": "json_response",
                    "next_url_path": "links.next",
                },
                "params": {
                    # the parameters below can optionally be configured
                    # "locale": "OPTIONAL_CONFIG",
                    # "creator": "OPTIONAL_CONFIG",
                    "page[size]": 100,
                },
            },
        },
        "ticket_events": {
            "name": "ticket_events",
            "table_name": "ticket_events",
            "primary_key": "id",
            "write_disposition": "merge",
            "endpoint": {
                "data_selector": "ticket_events",
                "path": "/api/v2/incremental/ticket_events",
                "params": {
                    "per_page": 1000,
                    "start_time": 0,
                    # Incrementality is disabled as we can't access end_time on the root object
                    # "start_time": {
                    #     "type": "incremental",
                    #     "cursor_path": "end_time",
                    #     "initial_value": 0,  # type: ignore
                    # },
                },
            },
        },
        "tickets": {
            "name": "tickets",
            "table_name": "tickets",
            "primary_key": "id",
            "write_disposition": "merge",
            "endpoint": {
                "data_selector": "tickets",
                "path": "/api/v2/incremental/tickets",
                "paginator": ZendeskTicketsIncrementalEndpointPaginator(),
                "params": {
                    "per_page": 1000,
                    "start_time": {
                        "type": "incremental",
                        "cursor_path": "generated_timestamp",
                        "initial_value": 0,  # type: ignore
                    },
                },
            },
        },
        "ticket_metric_events": {
            "name": "ticket_metric_events",
            "table_name": "ticket_metric_events",
            "primary_key": "id",
            "write_disposition": "merge",
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
                    #     "initial_value": 0,  # type: ignore
                    # },
                },
            },
        },
    }

    return resources[name]


class ZendeskTicketsIncrementalEndpointPaginator(BasePaginator):
    def update_state(self, response: Response) -> None:
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


class ZendeskIncrementalEndpointPaginator(BasePaginator):
    def update_state(self, response: Response) -> None:
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


@dlt.source(max_table_nesting=0)
def zendesk_source(
    subdomain: str,
    api_key: str,
    email_address: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    is_incremental: bool = False,
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
            "primary_key": "id",
            "write_disposition": "merge",
        },
        "resources": [get_resource(endpoint, is_incremental)],
    }

    yield from rest_api_resources(config, team_id, job_id)
