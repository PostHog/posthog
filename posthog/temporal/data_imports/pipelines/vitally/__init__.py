import base64
from dateutil import parser
from typing import Any, Optional
import dlt
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from dlt.sources.helpers.requests import Response, Request
import requests
from posthog.temporal.data_imports.pipelines.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.pipelines.rest_source.typing import EndpointResource


def get_resource(name: str, is_incremental: bool) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "Organizations": {
            "name": "Organizations",
            "table_name": "organizations",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/organizations",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",  # type: ignore
                        "convert": lambda x: parser.parse(x).timestamp(),
                    }
                    if is_incremental
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Accounts": {
            "name": "Accounts",
            "table_name": "accounts",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/accounts",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",  # type: ignore
                        "convert": lambda x: parser.parse(x).timestamp(),
                    }
                    if is_incremental
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Users": {
            "name": "Users",
            "table_name": "users",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/users",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",  # type: ignore
                        "convert": lambda x: parser.parse(x).timestamp(),
                    }
                    if is_incremental
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Conversations": {
            "name": "Conversations",
            "table_name": "conversations",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/conversations",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",  # type: ignore
                        "convert": lambda x: parser.parse(x).timestamp(),
                    }
                    if is_incremental
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Notes": {
            "name": "Notes",
            "table_name": "notes",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/notes",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",  # type: ignore
                        "convert": lambda x: parser.parse(x).timestamp(),
                    }
                    if is_incremental
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Projects": {
            "name": "Projects",
            "table_name": "projects",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/projects",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",  # type: ignore
                        "convert": lambda x: parser.parse(x).timestamp(),
                    }
                    if is_incremental
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Tasks": {
            "name": "Tasks",
            "table_name": "tasks",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/tasks",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",  # type: ignore
                        "convert": lambda x: parser.parse(x).timestamp(),
                    }
                    if is_incremental
                    else None,
                },
            },
            "table_format": "delta",
        },
        "NPS_Responses": {
            "name": "NPS_Responses",
            "table_name": "nps_responses",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/npsResponses",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",  # type: ignore
                        "convert": lambda x: parser.parse(x).timestamp(),
                    }
                    if is_incremental
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Custom_Objects": {
            "name": "Custom_Objects",
            "table_name": "custom_objects",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/customObjects",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",  # type: ignore
                        "convert": lambda x: parser.parse(x).timestamp(),
                    }
                    if is_incremental
                    else None,
                },
            },
            "table_format": "delta",
        },
    }

    return resources[name]


class VitallyPaginator(BasePaginator):
    def __init__(self) -> None:
        super().__init__()

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        current_source = dlt.current.get_source()
        resources = current_source.resources
        current_resource = next(iter(resources.values()))
        incremental = current_resource.incremental.incremental

        self._cursor = None

        if not res:
            self._has_next_page = False
            return

        if incremental:
            updated_at_str = res["results"][0]["updatedAt"]
            updated_at = parser.parse(updated_at_str).timestamp()
            start_value = parser.parse(incremental.start_value).timestamp()

            if start_value >= updated_at:
                self._has_next_page = False
                return

        if res["next"]:
            self._has_next_page = True
            self._cursor = res["next"]
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}

        request.params["from"] = self._cursor


def get_base_url(region: str, subdomain: Optional[str]) -> str:
    if region == "US" and subdomain:
        return f"https://{subdomain}.rest.vitally.io/"

    return "https://rest.vitally-eu.io/"


@dlt.source(max_table_nesting=0)
def vitally_source(
    secret_token: str,
    region: str,
    subdomain: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    is_incremental: bool = False,
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": get_base_url(region, subdomain),
            "auth": {
                "type": "http_basic",
                "username": secret_token,
                "password": "",
            },
            "paginator": VitallyPaginator(),
        },
        "resource_defaults": {
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
        },
        "resources": [get_resource(endpoint, is_incremental)],
    }

    yield from rest_api_resources(config, team_id, job_id)


def validate_credentials(secret_token: str, region: str, subdomain: Optional[str]) -> bool:
    basic_token = base64.b64encode(f"{secret_token}:".encode("ascii")).decode("ascii")
    res = requests.get(
        f"{get_base_url(region, subdomain)}resources/users?limit=1",
        headers={"Authorization": f"Basic {basic_token}"},
    )

    return res.status_code == 200
