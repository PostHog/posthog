import base64
from typing import Any

import dlt
import requests
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource

from products.data_warehouse.backend.models.external_table_definitions import get_dlt_mapping_for_external_table


class TwilioPaginator(BasePaginator):
    """Paginator for Twilio API that uses next_page_uri from response."""

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        res = response.json()
        self._next_page_uri = res.get("next_page_uri")
        self._has_next_page = self._next_page_uri is not None

    def update_request(self, request: Request) -> None:
        if self._next_page_uri:
            request.url = self._next_page_uri


def get_resource(
    name: str, should_use_incremental_field: bool, db_incremental_field_last_value: Any | None
) -> EndpointResource:
    """Get the endpoint resource configuration for a given Twilio resource."""
    base_params = {"PageSize": 100}

    incremental_params = {}
    if should_use_incremental_field and db_incremental_field_last_value:
        incremental_params["DateCreated>"] = db_incremental_field_last_value

    resources: dict[str, EndpointResource] = {
        "accounts": {
            "name": "accounts",
            "table_name": "accounts",
            "primary_key": "sid",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("twilio_accounts"),
            "endpoint": {
                "data_selector": "accounts",
                "path": "/2010-04-01/Accounts.json",
                "paginator": TwilioPaginator(),
                "params": base_params,
            },
            "table_format": "delta",
        },
        "addresses": {
            "name": "addresses",
            "table_name": "addresses",
            "primary_key": "sid",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("twilio_addresses"),
            "endpoint": {
                "data_selector": "addresses",
                "path": "/2010-04-01/Accounts/{account_sid}/Addresses.json",
                "paginator": TwilioPaginator(),
                "params": {**base_params, **incremental_params},
            },
            "table_format": "delta",
        },
        "calls": {
            "name": "calls",
            "table_name": "calls",
            "primary_key": "sid",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("twilio_calls"),
            "endpoint": {
                "data_selector": "calls",
                "path": "/2010-04-01/Accounts/{account_sid}/Calls.json",
                "paginator": TwilioPaginator(),
                "params": {**base_params, **incremental_params},
            },
            "table_format": "delta",
        },
        "conferences": {
            "name": "conferences",
            "table_name": "conferences",
            "primary_key": "sid",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("twilio_conferences"),
            "endpoint": {
                "data_selector": "conferences",
                "path": "/2010-04-01/Accounts/{account_sid}/Conferences.json",
                "paginator": TwilioPaginator(),
                "params": {**base_params, **incremental_params},
            },
            "table_format": "delta",
        },
        "messages": {
            "name": "messages",
            "table_name": "messages",
            "primary_key": "sid",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("twilio_messages"),
            "endpoint": {
                "data_selector": "messages",
                "path": "/2010-04-01/Accounts/{account_sid}/Messages.json",
                "paginator": TwilioPaginator(),
                "params": {**base_params, **incremental_params},
            },
            "table_format": "delta",
        },
        "available_phone_numbers_local": {
            "name": "available_phone_numbers_local",
            "table_name": "available_phone_numbers_local",
            "primary_key": "phone_number",
            "write_disposition": "replace",
            "columns": get_dlt_mapping_for_external_table("twilio_available_phone_numbers_local"),
            "endpoint": {
                "data_selector": "available_phone_numbers",
                "path": "/2010-04-01/Accounts/{account_sid}/AvailablePhoneNumbers/US/Local.json",
                "paginator": TwilioPaginator(),
                "params": base_params,
            },
            "table_format": "delta",
        },
        "available_phone_numbers_mobile": {
            "name": "available_phone_numbers_mobile",
            "table_name": "available_phone_numbers_mobile",
            "primary_key": "phone_number",
            "write_disposition": "replace",
            "columns": get_dlt_mapping_for_external_table("twilio_available_phone_numbers_mobile"),
            "endpoint": {
                "data_selector": "available_phone_numbers",
                "path": "/2010-04-01/Accounts/{account_sid}/AvailablePhoneNumbers/US/Mobile.json",
                "paginator": TwilioPaginator(),
                "params": base_params,
            },
            "table_format": "delta",
        },
        "available_phone_numbers_toll_free": {
            "name": "available_phone_numbers_toll_free",
            "table_name": "available_phone_numbers_toll_free",
            "primary_key": "phone_number",
            "write_disposition": "replace",
            "columns": get_dlt_mapping_for_external_table("twilio_available_phone_numbers_toll_free"),
            "endpoint": {
                "data_selector": "available_phone_numbers",
                "path": "/2010-04-01/Accounts/{account_sid}/AvailablePhoneNumbers/US/TollFree.json",
                "paginator": TwilioPaginator(),
                "params": base_params,
            },
            "table_format": "delta",
        },
        "usage_records": {
            "name": "usage_records",
            "table_name": "usage_records",
            "primary_key": ["account_sid", "category", "start_date"],
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "columns": get_dlt_mapping_for_external_table("twilio_usage_records"),
            "endpoint": {
                "data_selector": "usage_records",
                "path": "/2010-04-01/Accounts/{account_sid}/Usage/Records.json",
                "paginator": TwilioPaginator(),
                "params": base_params,
            },
            "table_format": "delta",
        },
    }

    return resources[name]


@dlt.source(max_table_nesting=0)
def twilio_source(
    account_sid: str,
    auth_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Any | None,
    should_use_incremental_field: bool = False,
):
    """Create a DLT source for Twilio API."""
    config: RESTAPIConfig = {
        "client": {
            "base_url": "https://api.twilio.com",
            "auth": {
                "type": "http_basic",
                "username": account_sid,
                "password": auth_token,
            },
            "paginator": TwilioPaginator(),
        },
        "resource_defaults": {
            "primary_key": "sid",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "params": {
                    "account_sid": account_sid,
                },
            },
        },
        "resources": [get_resource(endpoint, should_use_incremental_field, db_incremental_field_last_value)],
    }

    yield from rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)


def validate_credentials(account_sid: str, auth_token: str) -> bool:
    """Validate Twilio credentials by making a test API call."""
    basic_token = base64.b64encode(f"{account_sid}:{auth_token}".encode("ascii")).decode("ascii")
    res = requests.get(
        f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}.json",
        headers={"Authorization": f"Basic {basic_token}"},
    )

    return res.status_code == 200
