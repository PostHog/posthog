from typing import Any, Optional

import dlt
import requests
from dlt.sources.helpers.requests import Request
from dlt.sources.helpers.rest_client.paginators import BaseNextUrlPaginator

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource


class SendgridPaginator(BaseNextUrlPaginator):
    def update_state(self, response, data=None):
        if response.status_code != 200:
            self._next_reference = None
            return

        try:
            result = response.json()

            # Handle pagination metadata
            if "_metadata" in result and "next" in result["_metadata"]:
                self._next_reference = result["_metadata"]["next"]
            else:
                self._next_reference = None
        except Exception:
            self._next_reference = None

    def update_request(self, request: Request) -> None:
        if self._next_reference:
            if request.params is None:
                request.params = {}
            # Extract page_token from the next URL if present
            if "page_token=" in self._next_reference:
                page_token = self._next_reference.split("page_token=")[1].split("&")[0]
                request.params["page_token"] = page_token


def get_resource(name: str, should_use_incremental_field: bool, start_time: Optional[int]) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "campaigns": {
            "name": "campaigns",
            "table_name": "campaigns",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "result",
                "path": "/v3/marketing/campaigns",
                "params": {
                    "page_size": 100,
                },
            },
            "table_format": "delta",
        },
        "lists": {
            "name": "lists",
            "table_name": "lists",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "result",
                "path": "/v3/marketing/lists",
                "params": {
                    "page_size": 100,
                },
            },
            "table_format": "delta",
        },
        "contacts": {
            "name": "contacts",
            "table_name": "contacts",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "result",
                "path": "/v3/marketing/contacts",
                "params": {
                    "page_size": 100,
                },
            },
            "table_format": "delta",
        },
        "segments": {
            "name": "segments",
            "table_name": "segments",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "results",
                "path": "/v3/marketing/segments/2.0",
                "params": {
                    "page_size": 100,
                },
            },
            "table_format": "delta",
        },
        "singlesends": {
            "name": "singlesends",
            "table_name": "singlesends",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "result",
                "path": "/v3/marketing/singlesends",
                "params": {
                    "page_size": 100,
                },
            },
            "table_format": "delta",
        },
        "templates": {
            "name": "templates",
            "table_name": "templates",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "result",
                "path": "/v3/templates",
                "params": {
                    "page_size": 100,
                    "generations": "dynamic",
                },
            },
            "table_format": "delta",
        },
        "global_suppressions": {
            "name": "global_suppressions",
            "table_name": "global_suppressions",
            "primary_key": "email",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "$",
                "path": "/v3/suppression/unsubscribes",
                "params": {
                    "limit": 500,
                    "start_time": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": start_time or 0,  # type: ignore
                    }
                    if should_use_incremental_field and start_time
                    else None,
                },
            },
            "table_format": "delta",
        },
        "suppression_groups": {
            "name": "suppression_groups",
            "table_name": "suppression_groups",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "$",
                "path": "/v3/asm/groups",
            },
            "table_format": "delta",
        },
        "suppression_group_members": {
            "name": "suppression_group_members",
            "table_name": "suppression_group_members",
            "primary_key": ["group_id", "email"],
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "$",
                "path": "/v3/suppression/unsubscribes",
                "params": {
                    "limit": 500,
                    "start_time": {
                        "type": "incremental",
                        "cursor_path": "created_at",
                        "initial_value": start_time or 0,  # type: ignore
                    }
                    if should_use_incremental_field and start_time
                    else None,
                },
            },
            "table_format": "delta",
        },
        "blocks": {
            "name": "blocks",
            "table_name": "blocks",
            "primary_key": "email",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "$",
                "path": "/v3/suppression/blocks",
                "params": {
                    "limit": 500,
                    "start_time": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": start_time or 0,  # type: ignore
                    }
                    if should_use_incremental_field and start_time
                    else None,
                },
            },
            "table_format": "delta",
        },
        "bounces": {
            "name": "bounces",
            "table_name": "bounces",
            "primary_key": "email",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "$",
                "path": "/v3/suppression/bounces",
                "params": {
                    "limit": 500,
                    "start_time": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": start_time or 0,  # type: ignore
                    }
                    if should_use_incremental_field and start_time
                    else None,
                },
            },
            "table_format": "delta",
        },
        "invalid_emails": {
            "name": "invalid_emails",
            "table_name": "invalid_emails",
            "primary_key": "email",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "$",
                "path": "/v3/suppression/invalid_emails",
                "params": {
                    "limit": 500,
                    "start_time": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": start_time or 0,  # type: ignore
                    }
                    if should_use_incremental_field and start_time
                    else None,
                },
            },
            "table_format": "delta",
        },
        "spam_reports": {
            "name": "spam_reports",
            "table_name": "spam_reports",
            "primary_key": "email",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "$",
                "path": "/v3/suppression/spam_reports",
                "params": {
                    "limit": 500,
                    "start_time": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": start_time or 0,  # type: ignore
                    }
                    if should_use_incremental_field and start_time
                    else None,
                },
            },
            "table_format": "delta",
        },
    }
    return resources[name]


@dlt.source(max_table_nesting=0)
def sendgrid_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
):
    start_time = None
    if should_use_incremental_field and db_incremental_field_last_value:
        start_time = int(db_incremental_field_last_value)

    config: RESTAPIConfig = {
        "client": {
            "base_url": "https://api.sendgrid.com",
            "headers": {
                "Authorization": f"Bearer {api_key}",
            },
            "paginator": SendgridPaginator(),
        },
        "resource_defaults": {
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [get_resource(endpoint, should_use_incremental_field, start_time)],
    }

    yield from rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)


def validate_credentials(api_key: str) -> bool:
    res = requests.get(
        "https://api.sendgrid.com/v3/user/profile",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return res.status_code == 200
