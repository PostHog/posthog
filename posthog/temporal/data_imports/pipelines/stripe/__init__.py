from typing import Any, Optional
import dlt
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from dlt.sources.helpers.requests import Response, Request
from posthog.temporal.data_imports.pipelines.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.pipelines.rest_source.typing import EndpointResource
from posthog.warehouse.models.external_table_definitions import get_dlt_mapping_for_external_table
from stripe import StripeClient


def get_resource(name: str, is_incremental: bool) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "BalanceTransaction": {
            "name": "BalanceTransaction",
            "table_name": "balance_transaction",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "columns": get_dlt_mapping_for_external_table("stripe_balancetransaction"),  # type: ignore
            "endpoint": {
                "data_selector": "data",
                "path": "/v1/balance_transactions",
                "params": {
                    # the parameters below can optionally be configured
                    "created[gte]": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": 0,  # type: ignore
                    }
                    if is_incremental
                    else None,
                    # "currency": "OPTIONAL_CONFIG",
                    # "ending_before": "OPTIONAL_CONFIG",
                    # "expand": "OPTIONAL_CONFIG",
                    "limit": 100,
                    # "payout": "OPTIONAL_CONFIG",
                    # "source": "OPTIONAL_CONFIG",
                    # "starting_after": "OPTIONAL_CONFIG",
                    # "type": "OPTIONAL_CONFIG",
                },
            },
            "table_format": "delta",
        },
        "Charge": {
            "name": "Charge",
            "table_name": "charge",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "columns": get_dlt_mapping_for_external_table("stripe_charge"),  # type: ignore
            "endpoint": {
                "data_selector": "data",
                "path": "/v1/charges",
                "params": {
                    # the parameters below can optionally be configured
                    "created[gte]": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": 0,  # type: ignore
                    }
                    if is_incremental
                    else None,
                    # "customer": "OPTIONAL_CONFIG",
                    # "ending_before": "OPTIONAL_CONFIG",
                    # "expand": "OPTIONAL_CONFIG",
                    "limit": 100,
                    # "payment_intent": "OPTIONAL_CONFIG",
                    # "starting_after": "OPTIONAL_CONFIG",
                    # "transfer_group": "OPTIONAL_CONFIG",
                },
            },
            "table_format": "delta",
        },
        "Customer": {
            "name": "Customer",
            "table_name": "customer",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "columns": get_dlt_mapping_for_external_table("stripe_customer"),  # type: ignore
            "endpoint": {
                "data_selector": "data",
                "path": "/v1/customers",
                "params": {
                    # the parameters below can optionally be configured
                    "created[gte]": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": 0,  # type: ignore
                    }
                    if is_incremental
                    else None,
                    # "email": "OPTIONAL_CONFIG",
                    # "ending_before": "OPTIONAL_CONFIG",
                    # "expand": "OPTIONAL_CONFIG",
                    "limit": 100,
                    # "starting_after": "OPTIONAL_CONFIG",
                    # "test_clock": "OPTIONAL_CONFIG",
                },
            },
            "table_format": "delta",
        },
        "Invoice": {
            "name": "Invoice",
            "table_name": "invoice",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "columns": get_dlt_mapping_for_external_table("stripe_invoice"),  # type: ignore
            "endpoint": {
                "data_selector": "data",
                "path": "/v1/invoices",
                "params": {
                    # the parameters below can optionally be configured
                    # "collection_method": "OPTIONAL_CONFIG",
                    "created[gte]": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": 0,  # type: ignore
                    }
                    if is_incremental
                    else None,
                    # "customer": "OPTIONAL_CONFIG",
                    # "due_date": "OPTIONAL_CONFIG",
                    # "ending_before": "OPTIONAL_CONFIG",
                    # "expand": "OPTIONAL_CONFIG",
                    "limit": 100,
                    # "starting_after": "OPTIONAL_CONFIG",
                    # "status": "OPTIONAL_CONFIG",
                    # "subscription": "OPTIONAL_CONFIG",
                },
            },
            "table_format": "delta",
        },
        "Price": {
            "name": "Price",
            "table_name": "price",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "columns": get_dlt_mapping_for_external_table("stripe_price"),  # type: ignore
            "endpoint": {
                "data_selector": "data",
                "path": "/v1/prices",
                "params": {
                    # the parameters below can optionally be configured
                    # "active": "OPTIONAL_CONFIG",
                    "created[gte]": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": 0,  # type: ignore
                    }
                    if is_incremental
                    else None,
                    # "currency": "OPTIONAL_CONFIG",
                    # "ending_before": "OPTIONAL_CONFIG",
                    "expand[]": "data.tiers",
                    "limit": 100,
                    # "lookup_keys": "OPTIONAL_CONFIG",
                    # "product": "OPTIONAL_CONFIG",
                    # "recurring": "OPTIONAL_CONFIG",
                    # "starting_after": "OPTIONAL_CONFIG",
                    # "type": "OPTIONAL_CONFIG",
                },
            },
            "table_format": "delta",
        },
        "Product": {
            "name": "Product",
            "table_name": "product",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "columns": get_dlt_mapping_for_external_table("stripe_product"),  # type: ignore
            "endpoint": {
                "data_selector": "data",
                "path": "/v1/products",
                "params": {
                    # the parameters below can optionally be configured
                    # "active": "OPTIONAL_CONFIG",
                    "created[gte]": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": 0,  # type: ignore
                    }
                    if is_incremental
                    else None,
                    # "ending_before": "OPTIONAL_CONFIG",
                    # "expand": "OPTIONAL_CONFIG",
                    # "ids": "OPTIONAL_CONFIG",
                    "limit": 100,
                    # "shippable": "OPTIONAL_CONFIG",
                    # "starting_after": "OPTIONAL_CONFIG",
                    # "url": "OPTIONAL_CONFIG",
                },
            },
            "table_format": "delta",
        },
        "Subscription": {
            "name": "Subscription",
            "table_name": "subscription",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "columns": get_dlt_mapping_for_external_table("stripe_subscription"),  # type: ignore
            "endpoint": {
                "data_selector": "data",
                "path": "/v1/subscriptions",
                "params": {
                    # the parameters below can optionally be configured
                    # "collection_method": "OPTIONAL_CONFIG",
                    "created[gte]": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": 0,  # type: ignore
                    }
                    if is_incremental
                    else None,
                    # "current_period_end": "OPTIONAL_CONFIG",
                    # "current_period_start": "OPTIONAL_CONFIG",
                    # "customer": "OPTIONAL_CONFIG",
                    # "ending_before": "OPTIONAL_CONFIG",
                    # "expand": "OPTIONAL_CONFIG",
                    "limit": 100,
                    # "price": "OPTIONAL_CONFIG",
                    # "starting_after": "OPTIONAL_CONFIG",
                    "status": "all",
                    # "test_clock": "OPTIONAL_CONFIG",
                },
            },
            "table_format": "delta",
        },
    }

    return resources[name]


class StripePaginator(BasePaginator):
    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        self._starting_after = None

        if not res:
            self._has_next_page = False
            return

        if res["has_more"]:
            self._has_next_page = True

            earliest_value_in_response = res["data"][-1]["id"]
            self._starting_after = earliest_value_in_response
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}

        request.params["starting_after"] = self._starting_after


@dlt.source(max_table_nesting=0)
def stripe_source(
    api_key: str, account_id: Optional[str], endpoint: str, team_id: int, job_id: str, is_incremental: bool = False
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": "https://api.stripe.com/",
            "auth": {
                "type": "http_basic",
                "username": api_key,
                "password": "",
            },
            "headers": {
                "Stripe-Account": account_id,
            }
            if account_id is not None and len(account_id) > 0
            else None,
            "paginator": StripePaginator(),
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


def validate_credentials(api_key: str) -> bool:
    try:
        client = StripeClient(api_key)
        client.customers.list(params={"limit": 1})
        return True
    except:
        return False
