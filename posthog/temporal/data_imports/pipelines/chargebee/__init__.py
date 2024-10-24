import base64
from typing import Any, Optional

import dlt
import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from posthog.temporal.data_imports.pipelines.rest_source.typing import EndpointResource


def get_resource(name: str, is_incremental: bool) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "Customers": {
            "name": "Customers",
            "table_name": "customers",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "endpoint": {
                "data_selector": "list[*].customer",
                "path": "/v2/customers",
                "params": {
                    # the parameters below can optionally be configured
                    "updated_at[after]": {
                        "type": "incremental",
                        "cursor_path": "updated_at",
                        "initial_value": 0,  # type: ignore
                    }
                    if is_incremental
                    else None,
                    "limit": 100,
                    # by default, API does not return deleted resources
                    "include_deleted": True,
                },
            },
            "table_format": "delta",
        },
    }
    return resources[name]


@dlt.source(max_table_nesting=0)
def chargebee_source(
    api_key: str, site_name: str, endpoint: str, team_id: int, job_id: str, is_incremental: bool = False
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": f"https://{site_name}.chargebee.com/api",
            "auth": {
                "type": "http_basic",
                "username": api_key,
                "password": "",
            },
            # TODO
            # "paginator": StripePaginator(),
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


def validate_credentials(api_key: str, site_name: str) -> bool:
    basic_token = base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")
    res = requests.get(
        f"https://{site_name}.chargebee.com/api/v2/customers?limit=1",
        headers={"Authorization": f"Basic {basic_token}"},
    )
    return res.status_code == 200
