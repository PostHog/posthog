import dataclasses
from collections.abc import Callable
from typing import Any, Optional, Union

from stripe import ListObject, StripeClient
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.stripe.constants import (
    ACCOUNT_RESOURCE_NAME,
    BALANCE_TRANSACTION_RESOURCE_NAME,
    CHARGE_RESOURCE_NAME,
    CREDIT_NOTE_RESOURCE_NAME,
    CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
    CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    DISPUTE_RESOURCE_NAME,
    INVOICE_ITEM_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    PAYOUT_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    REFUND_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
)
from posthog.temporal.data_imports.sources.stripe.custom import InvoiceListWithAllLines
from posthog.temporal.data_imports.sources.stripe.settings import INCREMENTAL_FIELDS

from products.data_warehouse.backend.models.external_table_definitions import get_dlt_mapping_for_external_table

DEFAULT_LIMIT = 100


@dataclasses.dataclass
class StripeResource:
    method: Callable[..., ListObject[Any]]
    params: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class StripeNestedResource:
    method: Callable[..., ListObject[Any]]
    nested_parent_param: str
    parent_id: str
    parent: StripeResource
    params: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class StripeResumeConfig:
    starting_after: str


def get_rows(
    api_key: str,
    endpoint: str,
    account_id: Optional[str],
    db_incremental_field_last_value: Optional[Any],
    db_incremental_field_earliest_value: Optional[Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StripeResumeConfig],
    should_use_incremental_field: bool = False,
):
    client = StripeClient(api_key, stripe_account=account_id, stripe_version="2024-09-30.acacia", max_network_retries=2)
    default_params = {"limit": DEFAULT_LIMIT}
    resources: dict[str, Union[StripeResource, StripeNestedResource]] = {
        ACCOUNT_RESOURCE_NAME: StripeResource(method=client.accounts.list),
        BALANCE_TRANSACTION_RESOURCE_NAME: StripeResource(method=client.balance_transactions.list),
        CHARGE_RESOURCE_NAME: StripeResource(method=client.charges.list),
        CUSTOMER_RESOURCE_NAME: StripeResource(method=client.customers.list),
        DISPUTE_RESOURCE_NAME: StripeResource(method=client.disputes.list),
        INVOICE_ITEM_RESOURCE_NAME: StripeResource(method=client.invoice_items.list),
        INVOICE_RESOURCE_NAME: StripeResource(
            method=lambda params: InvoiceListWithAllLines(client, params, logger)  # type: ignore
        ),
        PAYOUT_RESOURCE_NAME: StripeResource(method=client.payouts.list),
        PRICE_RESOURCE_NAME: StripeResource(method=client.prices.list, params={"expand[]": "data.tiers"}),
        PRODUCT_RESOURCE_NAME: StripeResource(method=client.products.list),
        REFUND_RESOURCE_NAME: StripeResource(method=client.refunds.list),
        SUBSCRIPTION_RESOURCE_NAME: StripeResource(method=client.subscriptions.list, params={"status": "all"}),
        CREDIT_NOTE_RESOURCE_NAME: StripeResource(method=client.credit_notes.list),
        CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME: StripeNestedResource(
            method=client.customers.balance_transactions.list,
            nested_parent_param="customer",
            parent_id="id",
            parent=StripeResource(method=client.customers.list),
        ),
        CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME: StripeNestedResource(
            method=client.customers.payment_methods.list,
            nested_parent_param="customer",
            parent_id="id",
            parent=StripeResource(method=client.customers.list),
        ),
    }

    batcher = Batcher(logger=logger)

    resource = resources.get(endpoint, None)
    if not resource:
        raise Exception(f"Stripe endpoint does not exist: {endpoint}")

    logger.debug(f"Stripe: reading from resource {resource}")

    # Get the incremental field name for this endpoint
    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else "created"

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.is_resumable() else None

    if (
        not should_use_incremental_field
        or (db_incremental_field_last_value is None and db_incremental_field_earliest_value is None)
        or isinstance(resource, StripeNestedResource)
    ):
        logger.debug(f"Stripe: iterating all objects from resource")
        resume_params = {}
        if resume_config is not None:
            resume_params = {"starting_after": resume_config.starting_after}
            logger.debug(f"Stripe: resuming from object id: {resume_config.starting_after}")

        if isinstance(resource, StripeNestedResource):
            stripe_parent_objects = resource.parent.method(
                params={**default_params, **resource.parent.params, **resume_params}
            )
            for obj in stripe_parent_objects.auto_paging_iter():
                stripe_nested_objects = resource.method(
                    **{resource.nested_parent_param: obj[resource.parent_id]},
                    params={**default_params, **resource.params},
                )
                for nested_obj in stripe_nested_objects.auto_paging_iter():  # noqa: UP028
                    batcher.batch(
                        {
                            **nested_obj,
                            **{resource.nested_parent_param: obj[resource.parent_id]},
                        }
                    )

                    if batcher.should_yield():
                        py_table = batcher.get_table()
                        yield py_table

                        last_cur = py_table.column("id")[-1].as_py()
                        resumable_source_manager.save_state(StripeResumeConfig(starting_after=last_cur))
        else:
            stripe_objects = resource.method(params={**default_params, **resource.params, **resume_params})
            for obj in stripe_objects.auto_paging_iter():
                batcher.batch(obj)

                if batcher.should_yield():
                    py_table = batcher.get_table()
                    yield py_table

                    last_cur = py_table.column("id")[-1].as_py()
                    resumable_source_manager.save_state(StripeResumeConfig(starting_after=last_cur))

        if batcher.should_yield(include_incomplete_chunk=True):
            py_table = batcher.get_table()
            yield py_table

            last_cur = py_table.column("id")[-1].as_py()
            resumable_source_manager.save_state(StripeResumeConfig(starting_after=last_cur))

        return

    # check for any objects less than the minimum object we already have
    if db_incremental_field_earliest_value is not None:
        logger.debug(
            f"Stripe: iterating earliest objects from resource: created[lt] = {db_incremental_field_earliest_value}"
        )

        stripe_objects = resource.method(
            params={
                **default_params,
                **resource.params,
                f"created[lt]": db_incremental_field_earliest_value,
            }
        )
        yield from stripe_objects.auto_paging_iter()

    # check for any objects more than the maximum object we already have
    if db_incremental_field_last_value is not None:
        logger.debug(f"Stripe: iterating latest objects from resource: created[gt] = {db_incremental_field_last_value}")

        stripe_objects = resource.method(
            params={
                **default_params,
                **resource.params,
                f"created[gt]": db_incremental_field_last_value,
            }
        )
        for obj in stripe_objects.auto_paging_iter():
            if obj[incremental_field_name] <= db_incremental_field_last_value:
                break

            yield obj


def stripe_source(
    api_key: str,
    account_id: Optional[str],
    endpoint: str,
    db_incremental_field_last_value: Optional[Any],
    db_incremental_field_earliest_value: Optional[Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StripeResumeConfig],
    should_use_incremental_field: bool = False,
):
    column_mapping = get_dlt_mapping_for_external_table(f"stripe_{endpoint.lower()}")
    column_hints = {key: value.get("data_type") for key, value in column_mapping.items()}

    # Get the incremental field name for partition keys
    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else "created"

    return SourceResponse(
        items=lambda: get_rows(
            api_key=api_key,
            account_id=account_id,
            endpoint=endpoint,
            db_incremental_field_last_value=db_incremental_field_last_value,
            db_incremental_field_earliest_value=db_incremental_field_earliest_value,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=["id"],
        name=endpoint,
        column_hints=column_hints,
        # Stripe data is returned in descending timestamp order
        sort_mode="desc",
        partition_count=1,  # this enables partitioning
        partition_size=1,  # this enables partitioning
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[incremental_field_name],
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
        {"name": DISPUTE_RESOURCE_NAME, "method": client.disputes.list, "params": {"limit": 1}},
        {"name": INVOICE_ITEM_RESOURCE_NAME, "method": client.invoice_items.list, "params": {"limit": 1}},
        {"name": INVOICE_RESOURCE_NAME, "method": client.invoices.list, "params": {"limit": 1}},
        {"name": PAYOUT_RESOURCE_NAME, "method": client.payouts.list, "params": {"limit": 1}},
        {"name": PRICE_RESOURCE_NAME, "method": client.prices.list, "params": {"limit": 1}},
        {"name": PRODUCT_RESOURCE_NAME, "method": client.products.list, "params": {"limit": 1}},
        {"name": SUBSCRIPTION_RESOURCE_NAME, "method": client.subscriptions.list, "params": {"limit": 1}},
        {"name": REFUND_RESOURCE_NAME, "method": client.refunds.list, "params": {"limit": 1}},
        {"name": CREDIT_NOTE_RESOURCE_NAME, "method": client.credit_notes.list, "params": {"limit": 1}},
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
