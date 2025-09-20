import base64
from datetime import datetime
from typing import Any, Optional

import requests
from dateutil import parser
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "Organizations": {
            "name": "Organizations",
            "table_name": "organizations",
            **({"primary_key": "id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
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
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Accounts": {
            "name": "Accounts",
            "table_name": "accounts",
            **({"primary_key": "id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/resources/accounts",
                "params": {
                    "limit": 100,
                    "sortBy": "updatedAt",
                    "status": "activeOrChurned",
                    "updatedAt": {
                        "type": "incremental",
                        "cursor_path": "updatedAt",
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Users": {
            "name": "Users",
            "table_name": "users",
            **({"primary_key": "id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
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
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Conversations": {
            "name": "Conversations",
            "table_name": "conversations",
            **({"primary_key": "id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
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
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Notes": {
            "name": "Notes",
            "table_name": "notes",
            **({"primary_key": "id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
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
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Projects": {
            "name": "Projects",
            "table_name": "projects",
            **({"primary_key": "id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
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
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Tasks": {
            "name": "Tasks",
            "table_name": "tasks",
            **({"primary_key": "id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
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
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "NPS_Responses": {
            "name": "NPS_Responses",
            "table_name": "nps_responses",
            **({"primary_key": "id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
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
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
        "Custom_Objects": {
            "name": "Custom_Objects",
            "table_name": "custom_objects",
            **({"primary_key": "id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
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
                        "initial_value": "1970-01-01",
                        "convert": lambda x: parser.parse(x).timestamp() if not isinstance(x, datetime) else x,
                    }
                    if should_use_incremental_field
                    else None,
                },
            },
            "table_format": "delta",
        },
    }

    return resources[name]


class VitallyPaginator(BasePaginator):
    _incremental_start_value: Any
    _should_use_incremental_field: bool = False
    _cursor: str | None = None

    def __init__(self, incremental_start_value: Any, should_use_incremental_field: bool) -> None:
        self._incremental_start_value = incremental_start_value
        self._should_use_incremental_field = should_use_incremental_field

        super().__init__()

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        self._cursor = None

        if not res:
            self._has_next_page = False
            return

        if self._should_use_incremental_field and self._incremental_start_value is not None:
            updated_at_str = res["results"][0]["updatedAt"]
            updated_at = parser.parse(updated_at_str).timestamp()
            if isinstance(self._incremental_start_value, str):
                start_value = parser.parse(self._incremental_start_value).timestamp()
            elif isinstance(self._incremental_start_value, datetime):
                start_value = self._incremental_start_value.timestamp()
            else:
                raise TypeError("_incremental_start_value type is not supported for Vitally paginator")

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


def get_messages(
    secret_token: str,
    region: str,
    subdomain: Optional[str],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
):
    """Messages are a field on conversations which only get returned
    when you request each conversation individually. This queries
    for conversations and then gets and yields the messages for each
    conversation."""

    paginator = VitallyPaginator(
        incremental_start_value=db_incremental_field_last_value,
        should_use_incremental_field=should_use_incremental_field,
    )
    basic_token = base64.b64encode(f"{secret_token}:".encode("ascii")).decode("ascii")

    params: dict[str, Any] = {
        "limit": 100,
        "sortBy": "updatedAt",
    }

    if should_use_incremental_field:
        if db_incremental_field_last_value:
            params["updatedAt"] = (
                parser.parse(db_incremental_field_last_value).timestamp()
                if not isinstance(db_incremental_field_last_value, datetime)
                else db_incremental_field_last_value
            )
        else:
            params["updatedAt"] = "1970-01-01"

    request = requests.Request(
        "get",
        url=f"{get_base_url(region, subdomain)}resources/conversations",
        params=params,
        headers={"Authorization": f"Basic {basic_token}:"},
    )

    logger.debug("Requesting first page")

    with requests.session() as session:
        while paginator.has_next_page:
            paginator.update_request(request)
            prepared_request = session.prepare_request(request)
            response = session.send(prepared_request)
            logger.debug(f"Requesting {prepared_request.url}")

            json = response.json()
            results = json["results"]

            for conversation in results:
                id = conversation.get("id")
                conversation_updated_at = conversation.get("updatedAt")
                logger.debug(f"Requesting messages for conversation {id}")

                conversation_response = requests.get(
                    f"{get_base_url(region, subdomain)}resources/conversations/{id}",
                    headers={"Authorization": f"Basic {basic_token}:"},
                )
                messages = conversation_response.json().get("messages") or []
                logger.debug(f"Yielding {len(messages)} messages")
                for message in messages:
                    message["conversation_updated_at"] = conversation_updated_at
                    yield message

            paginator.update_state(response)


def get_base_url(region: str, subdomain: Optional[str]) -> str:
    if region == "US" and subdomain:
        return f"https://{subdomain}.rest.vitally.io/"

    return "https://rest.vitally-eu.io/"


def vitally_source(
    secret_token: str,
    region: str,
    subdomain: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
):
    if endpoint == "Messages":
        yield from get_messages(
            secret_token, region, subdomain, db_incremental_field_last_value, should_use_incremental_field, logger
        )
        return

    config: RESTAPIConfig = {
        "client": {
            "base_url": get_base_url(region, subdomain),
            "auth": {
                "type": "http_basic",
                "username": secret_token,
                "password": "",
            },
            "paginator": VitallyPaginator(
                incremental_start_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
            ),
        },
        "resource_defaults": {
            **({"primary_key": "id"} if should_use_incremental_field else {}),
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    dlt_resources = rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)
    yield from dlt_resources[0]


def validate_credentials(secret_token: str, region: str, subdomain: Optional[str]) -> bool:
    basic_token = base64.b64encode(f"{secret_token}:".encode("ascii")).decode("ascii")
    res = requests.get(
        f"{get_base_url(region, subdomain)}resources/users?limit=1",
        headers={"Authorization": f"Basic {basic_token}"},
    )

    return res.status_code == 200
