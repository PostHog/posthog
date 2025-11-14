from typing import Any, Optional
import logging

import dlt
import requests
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from dlt.sources.helpers.requests import Request, Response

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource

from products.data_warehouse.backend.models.external_table_definitions import get_dlt_mapping_for_external_table


class IntercomPaginator(BasePaginator):
    """Paginator for Intercom API using cursor-based pagination"""

    def __init__(self):
        super().__init__()
        self._next_page = None

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        if not res:
            self._has_next_page = False
            return

        # Intercom uses pages.next for pagination
        pages = res.get("pages", {})
        self._next_page = pages.get("next")

        if self._next_page:
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._next_page:
            if request.params is None:
                request.params = {}
            request.params["starting_after"] = self._next_page


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    """Define endpoint resources for each Intercom endpoint"""

    resources: dict[str, EndpointResource] = {
        "admins": {
            "name": "admins",
            "table_name": "admins",
            "primary_key": "id",
            "write_disposition": "replace",
            "columns": get_dlt_mapping_for_external_table("intercom_admins"),
            "endpoint": {
                "data_selector": "admins",
                "path": "/admins",
                "paginator": IntercomPaginator(),
                "params": {
                    "per_page": 150,
                },
            },
            "table_format": "delta",
        },
        "companies": {
            "name": "companies",
            "table_name": "companies",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("intercom_companies"),
            "endpoint": {
                "data_selector": "data",
                "path": "/companies/scroll",
                "paginator": IntercomScrollPaginator(),
            },
            "table_format": "delta",
        },
        "company_attributes": {
            "name": "company_attributes",
            "table_name": "company_attributes",
            "primary_key": "name",
            "write_disposition": "replace",
            "columns": get_dlt_mapping_for_external_table("intercom_company_attributes"),
            "endpoint": {
                "data_selector": "data",
                "path": "/data_attributes",
                "params": {
                    "model": "company",
                },
            },
            "table_format": "delta",
        },
        "contacts": {
            "name": "contacts",
            "table_name": "contacts",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("intercom_contacts"),
            "endpoint": {
                "data_selector": "data",
                "path": "/contacts",
                "paginator": IntercomPaginator(),
                "params": {
                    "per_page": 150,
                },
            },
            "table_format": "delta",
        },
        "contact_attributes": {
            "name": "contact_attributes",
            "table_name": "contact_attributes",
            "primary_key": "name",
            "write_disposition": "replace",
            "columns": get_dlt_mapping_for_external_table("intercom_contact_attributes"),
            "endpoint": {
                "data_selector": "data",
                "path": "/data_attributes",
                "params": {
                    "model": "contact",
                },
            },
            "table_format": "delta",
        },
        "conversations": {
            "name": "conversations",
            "table_name": "conversations",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("intercom_conversations"),
            "endpoint": {
                "data_selector": "conversations",
                "path": "/conversations",
                "paginator": IntercomPaginator(),
                "params": {
                    "per_page": 150,
                },
            },
            "table_format": "delta",
        },
        "segments": {
            "name": "segments",
            "table_name": "segments",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("intercom_segments"),
            "endpoint": {
                "data_selector": "segments",
                "path": "/segments",
                "paginator": IntercomPaginator(),
                "params": {
                    "per_page": 150,
                },
            },
            "table_format": "delta",
        },
        "tags": {
            "name": "tags",
            "table_name": "tags",
            "primary_key": "id",
            "write_disposition": "replace",
            "columns": get_dlt_mapping_for_external_table("intercom_tags"),
            "endpoint": {
                "data_selector": "data",
                "path": "/tags",
            },
            "table_format": "delta",
        },
        "teams": {
            "name": "teams",
            "table_name": "teams",
            "primary_key": "id",
            "write_disposition": "replace",
            "columns": get_dlt_mapping_for_external_table("intercom_teams"),
            "endpoint": {
                "data_selector": "teams",
                "path": "/teams",
            },
            "table_format": "delta",
        },
        "tickets": {
            "name": "tickets",
            "table_name": "tickets",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("intercom_tickets"),
            "endpoint": {
                "data_selector": "tickets",
                "path": "/tickets",
                "paginator": IntercomPaginator(),
                "params": {
                    "per_page": 150,
                },
            },
            "table_format": "delta",
        },
    }

    return resources[name]


class IntercomScrollPaginator(BasePaginator):
    """Paginator for Intercom scroll endpoints (used by companies)"""

    def __init__(self):
        super().__init__()
        self._scroll_param = None

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        if not res:
            self._has_next_page = False
            return

        # Intercom scroll endpoints use scroll_param for pagination
        self._scroll_param = res.get("scroll_param")

        if self._scroll_param:
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._scroll_param:
            if request.params is None:
                request.params = {}
            request.params["scroll_param"] = self._scroll_param


def validate_credentials(access_token: str) -> bool:
    """Validate Intercom access token by making a test API call"""
    try:
        response = requests.get(
            "https://api.intercom.io/admins",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "Intercom-Version": "2.11",
            },
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


@dlt.source(max_table_nesting=0)
def _intercom_dlt_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
    logger: Optional[logging.Logger] = None,
):
    """Create a DLT source for Intercom API"""

    config: RESTAPIConfig = {
        "client": {
            "base_url": "https://api.intercom.io/",
            "auth": {
                "type": "bearer",
                "token": access_token,
            },
            "headers": {
                "Accept": "application/json",
                "Intercom-Version": "2.11",
            },
        },
        "resources": [
            get_resource(
                endpoint,
                should_use_incremental_field=should_use_incremental_field,
            )
        ],
    }

    yield from rest_api_resources(config)


def intercom_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    logger: Optional[logging.Logger] = None,
) -> SourceResponse:
    """Wrapper function that returns a SourceResponse for the pipeline"""

    source = _intercom_dlt_source(
        access_token=access_token,
        endpoint=endpoint,
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=db_incremental_field_last_value,
        should_use_incremental_field=should_use_incremental_field,
        logger=logger,
    )

    # Get primary keys from the resource definition
    resource = get_resource(endpoint, should_use_incremental_field)
    primary_key = resource.get("primary_key", "id")

    return SourceResponse(
        items=source,
        primary_keys=[primary_key] if isinstance(primary_key, str) else primary_key,
    )
