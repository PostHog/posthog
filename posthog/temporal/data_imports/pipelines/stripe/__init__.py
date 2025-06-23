import dataclasses
from typing import Any, Optional
from collections.abc import Callable

import dlt
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from stripe import ListObject, StripeClient

from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from posthog.temporal.data_imports.pipelines.rest_source.typing import EndpointResource
from posthog.warehouse.models.external_table_definitions import (
    get_dlt_mapping_for_external_table,
)
from posthog.temporal.data_imports.pipelines.stripe.constants import (
    ACCOUNT_RESOURCE_NAME,
    BALANCE_TRANSACTION_RESOURCE_NAME,
    CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
)

DEFAULT_LIMIT = 100


def get_resource(name: str, is_incremental: bool) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        ACCOUNT_RESOURCE_NAME: {
            "name": ACCOUNT_RESOURCE_NAME,
            "table_name": "account",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "columns": get_dlt_mapping_for_external_table("stripe_account"),
            "endpoint": {
                "data_selector": "data",
                "path": "/v1/accounts",
                "params": {
                    # the parameters below can optionally be configured
                    "created[gt]": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": 0,  # type: ignore
                    }
                    if is_incremental
                    else None,
                    # "currency": "OPTIONAL_CONFIG",
                    # "ending_before": "OPTIONAL_CONFIG",
                    # "expand": "OPTIONAL_CONFIG",
                    "limit": DEFAULT_LIMIT,
                    # "payout": "OPTIONAL_CONFIG",
                    # "source": "OPTIONAL_CONFIG",
                    # "starting_after": "OPTIONAL_CONFIG",
                    # "type": "OPTIONAL_CONFIG",
                },
            },
            "table_format": "delta",
        },
        BALANCE_TRANSACTION_RESOURCE_NAME: {
            "name": BALANCE_TRANSACTION_RESOURCE_NAME,
            "table_name": "balance_transaction",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "columns": get_dlt_mapping_for_external_table("stripe_balancetransaction"),
            "endpoint": {
                "data_selector": "data",
                "path": "/v1/balance_transactions",
                "params": {
                    # the parameters below can optionally be configured
                    "created[gt]": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": 0,  # type: ignore
                    }
                    if is_incremental
                    else None,
                    # "currency": "OPTIONAL_CONFIG",
                    # "ending_before": "OPTIONAL_CONFIG",
                    # "expand": "OPTIONAL_CONFIG",
                    "limit": DEFAULT_LIMIT,
                    # "payout": "OPTIONAL_CONFIG",
                    # "source": "OPTIONAL_CONFIG",
                    # "starting_after": "OPTIONAL_CONFIG",
                    # "type": "OPTIONAL_CONFIG",
                },
            },
            "table_format": "delta",
        },
        CHARGE_RESOURCE_NAME: {
            "name": CHARGE_RESOURCE_NAME,
            "table_name": "charge",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "columns": get_dlt_mapping_for_external_table("stripe_charge"),
            "endpoint": {
                "data_selector": "data",
                "path": "/v1/charges",
                "params": {
                    # the parameters below can optionally be configured
                    "created[gt]": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": 0,  # type: ignore
                    }
                    if is_incremental
                    else None,
                    # "customer": "OPTIONAL_CONFIG",
                    # "ending_before": "OPTIONAL_CONFIG",
                    # "expand": "OPTIONAL_CONFIG",
                    "limit": DEFAULT_LIMIT,
                    # "payment_intent": "OPTIONAL_CONFIG",
                    # "starting_after": "OPTIONAL_CONFIG",
                    # "transfer_group": "OPTIONAL_CONFIG",
                },
            },
            "table_format": "delta",
        },
        CUSTOMER_RESOURCE_NAME: {
            "name": CUSTOMER_RESOURCE_NAME,
            "table_name": "customer",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "columns": get_dlt_mapping_for_external_table("stripe_customer"),
            "endpoint": {
                "data_selector": "data",
                "path": "/v1/customers",
                "params": {
                    # the parameters below can optionally be configured
                    "created[gt]": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": 0,  # type: ignore
                    }
                    if is_incremental
                    else None,
                    # "email": "OPTIONAL_CONFIG",
                    # "ending_before": "OPTIONAL_CONFIG",
                    # "expand": "OPTIONAL_CONFIG",
                    "limit": DEFAULT_LIMIT,
                    # "starting_after": "OPTIONAL_CONFIG",
                    # "test_clock": "OPTIONAL_CONFIG",
                },
            },
            "table_format": "delta",
        },
        INVOICE_RESOURCE_NAME: {
            "name": INVOICE_RESOURCE_NAME,
            "table_name": "invoice",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "columns": get_dlt_mapping_for_external_table("stripe_invoice"),
            "endpoint": {
                "data_selector": "data",
                "path": "/v1/invoices",
                "params": {
                    # the parameters below can optionally be configured
                    # "collection_method": "OPTIONAL_CONFIG",
                    "created[gt]": {
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
                    "limit": DEFAULT_LIMIT,
                    # "starting_after": "OPTIONAL_CONFIG",
                    # "status": "OPTIONAL_CONFIG",
                    # "subscription": "OPTIONAL_CONFIG",
                },
            },
            "table_format": "delta",
        },
        PRICE_RESOURCE_NAME: {
            "name": PRICE_RESOURCE_NAME,
            "table_name": "price",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "columns": get_dlt_mapping_for_external_table("stripe_price"),
            "endpoint": {
                "data_selector": "data",
                "path": "/v1/prices",
                "params": {
                    # the parameters below can optionally be configured
                    # "active": "OPTIONAL_CONFIG",
                    "created[gt]": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": 0,  # type: ignore
                    }
                    if is_incremental
                    else None,
                    # "currency": "OPTIONAL_CONFIG",
                    # "ending_before": "OPTIONAL_CONFIG",
                    "expand[]": "data.tiers",
                    "limit": DEFAULT_LIMIT,
                    # "lookup_keys": "OPTIONAL_CONFIG",
                    # "product": "OPTIONAL_CONFIG",
                    # "recurring": "OPTIONAL_CONFIG",
                    # "starting_after": "OPTIONAL_CONFIG",
                    # "type": "OPTIONAL_CONFIG",
                },
            },
            "table_format": "delta",
        },
        PRODUCT_RESOURCE_NAME: {
            "name": PRODUCT_RESOURCE_NAME,
            "table_name": "product",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "columns": get_dlt_mapping_for_external_table("stripe_product"),
            "endpoint": {
                "data_selector": "data",
                "path": "/v1/products",
                "params": {
                    # the parameters below can optionally be configured
                    # "active": "OPTIONAL_CONFIG",
                    "created[gt]": {
                        "type": "incremental",
                        "cursor_path": "created",
                        "initial_value": 0,  # type: ignore
                    }
                    if is_incremental
                    else None,
                    # "ending_before": "OPTIONAL_CONFIG",
                    # "expand": "OPTIONAL_CONFIG",
                    # "ids": "OPTIONAL_CONFIG",
                    "limit": DEFAULT_LIMIT,
                    # "shippable": "OPTIONAL_CONFIG",
                    # "starting_after": "OPTIONAL_CONFIG",
                    # "url": "OPTIONAL_CONFIG",
                },
            },
            "table_format": "delta",
        },
        SUBSCRIPTION_RESOURCE_NAME: {
            "name": SUBSCRIPTION_RESOURCE_NAME,
            "table_name": "subscription",
            "primary_key": "id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "columns": get_dlt_mapping_for_external_table("stripe_subscription"),
            "endpoint": {
                "data_selector": "data",
                "path": "/v1/subscriptions",
                "params": {
                    # the parameters below can optionally be configured
                    # "collection_method": "OPTIONAL_CONFIG",
                    "created[gt]": {
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
                    "limit": DEFAULT_LIMIT,
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


@dataclasses.dataclass
class StripeResource:
    method: Callable[..., ListObject[Any]]
    params: dict[str, Any] = dataclasses.field(default_factory=dict)


def stripe_source_v2(
    api_key: str,
    account_id: Optional[str],
    endpoint: str,
    db_incremental_field_last_value: Optional[Any],
    db_incremental_field_earliest_value: Optional[Any],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
):
    def get_rows():
        client = StripeClient(api_key, stripe_account=account_id, stripe_version="2024-09-30.acacia")
        default_params = {"limit": DEFAULT_LIMIT}
        resources: dict[str, StripeResource] = {
            ACCOUNT_RESOURCE_NAME: StripeResource(method=client.accounts.list),
            BALANCE_TRANSACTION_RESOURCE_NAME: StripeResource(method=client.balance_transactions.list),
            CHARGE_RESOURCE_NAME: StripeResource(method=client.charges.list),
            CUSTOMER_RESOURCE_NAME: StripeResource(method=client.customers.list),
            INVOICE_RESOURCE_NAME: StripeResource(method=client.invoices.list),
            PRICE_RESOURCE_NAME: StripeResource(method=client.prices.list, params={"expand[]": "data.tiers"}),
            PRODUCT_RESOURCE_NAME: StripeResource(method=client.products.list),
            SUBSCRIPTION_RESOURCE_NAME: StripeResource(method=client.subscriptions.list, params={"status": "all"}),
        }

        resource = resources.get(endpoint, None)
        if not resource:
            raise Exception(f"Stripe endpoint does not exist: {endpoint}")

        logger.debug(f"Stripe: reading from resource {resource}")

        if not should_use_incremental_field or (
            db_incremental_field_last_value is None and db_incremental_field_earliest_value is None
        ):
            logger.debug(f"Stripe: iterating all objects from resource")

            stripe_objects = resource.method(params={**default_params, **resource.params})
            yield from stripe_objects.auto_paging_iter()
            return

        # check for any objects less than the minimum object we already have
        if db_incremental_field_earliest_value is not None:
            logger.debug(
                f"Stripe: iterating earliest objects from resource: created[lt] = {db_incremental_field_earliest_value}"
            )

            stripe_objects = resource.method(
                params={**default_params, **resource.params, "created[lt]": db_incremental_field_earliest_value}
            )
            yield from stripe_objects.auto_paging_iter()

        # check for any objects more than the maximum object we already have
        if db_incremental_field_last_value is not None:
            logger.debug(
                f"Stripe: iterating latest objects from resource: created[gt] = {db_incremental_field_last_value}"
            )

            stripe_objects = resource.method(
                params={**default_params, **resource.params, "created[gt]": db_incremental_field_last_value}
            )
            for obj in stripe_objects.auto_paging_iter():
                if obj["created"] <= db_incremental_field_last_value:
                    break

                yield obj

    column_mapping = get_dlt_mapping_for_external_table(f"stripe_{endpoint.lower()}")
    column_hints = {key: value.get("data_type") for key, value in column_mapping.items()}

    return SourceResponse(
        items=get_rows(),
        primary_keys=["id"],
        name=endpoint,
        column_hints=column_hints,
        # Stripe data is returned in descending timestamp order
        sort_mode="desc",
        partition_count=1,  # this enables partitioning
        partition_size=1,  # this enables partitioning
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["created"],
    )


@dlt.source(max_table_nesting=0)
def stripe_dlt_source(
    api_key: str,
    account_id: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    is_incremental: bool = False,
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
                "Stripe-Version": "2024-09-30.acacia",
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

    yield from rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)


def stripe_source(
    api_key: str,
    account_id: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    is_incremental: bool = False,
):
    from posthog.temporal.data_imports.pipelines.pipeline.utils import (
        _get_column_hints,
        _get_primary_keys,
    )

    dlt_source = stripe_dlt_source(
        api_key, account_id, endpoint, team_id, job_id, db_incremental_field_last_value, is_incremental
    )
    resources = list(dlt_source.resources.items())
    assert len(resources) == 1
    resource_name, resource = resources[0]
    return SourceResponse(
        items=resource,
        primary_keys=_get_primary_keys(resource),
        name=resource_name,
        column_hints=_get_column_hints(resource),
        # Stripe data is returned in descending timestamp order
        sort_mode="desc",
        partition_count=1,  # this enables partitioning
        partition_size=1,  # this enables partitioning
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["created"],
    )


class StripePermissionError(Exception):
    """Exception raised when Stripe API key lacks permissions for specific resources."""

    def __init__(self, missing_permissions: dict[str, str]):
        self.missing_permissions = missing_permissions
        message = f"Stripe API key lacks permissions for: {', '.join(missing_permissions.keys())}"
        super().__init__(message)


def validate_credentials(api_key: str) -> bool:
    """
    Validates Stripe API credentials and checks permissions for all required resources.
    This function will:
    - Return True if the API key is valid and has all required permissions
    - Raise StripePermissionError if the API key is valid but lacks permissions for specific resources
    - Raise Exception if the API key is invalid or there's any other error
    """
    client = StripeClient(api_key)

    # Test access to all resources we're pulling
    resources_to_check = [
        {"name": ACCOUNT_RESOURCE_NAME, "method": client.accounts.list, "params": {"limit": 1}},
        {"name": BALANCE_TRANSACTION_RESOURCE_NAME, "method": client.balance_transactions.list, "params": {"limit": 1}},
        {"name": CHARGE_RESOURCE_NAME, "method": client.charges.list, "params": {"limit": 1}},
        {"name": CUSTOMER_RESOURCE_NAME, "method": client.customers.list, "params": {"limit": 1}},
        {"name": INVOICE_RESOURCE_NAME, "method": client.invoices.list, "params": {"limit": 1}},
        {"name": PRICE_RESOURCE_NAME, "method": client.prices.list, "params": {"limit": 1}},
        {"name": PRODUCT_RESOURCE_NAME, "method": client.products.list, "params": {"limit": 1}},
        {"name": SUBSCRIPTION_RESOURCE_NAME, "method": client.subscriptions.list, "params": {"limit": 1}},
    ]

    missing_permissions = {}

    for resource in resources_to_check:
        try:
            # This will raise an exception if we don't have access
            resource["method"](params=resource["params"])  # type: ignore
        except Exception as e:
            # Store the resource name and error message
            missing_permissions[resource["name"]] = str(e)

    if missing_permissions:
        raise StripePermissionError(missing_permissions)  # type: ignore

    return True
