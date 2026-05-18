import os
import re
import dataclasses
from collections.abc import Callable
from typing import Any, Optional, Union, cast, get_args, get_type_hints

import orjson
import stripe as stripe_lib
import pyarrow as pa
from asgiref.sync import async_to_sync
from stripe import ListObject, RequestsClient, StripeClient
from stripe._base_address import BaseAddresses
from stripe._webhook_endpoint_service import WebhookEndpointService
from structlog.types import FilteringBoundLogger

from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from posthog.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
)
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
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
    RESOURCE_TO_STRIPE_WEBHOOK_EVENT,
    SUBSCRIPTION_RESOURCE_NAME,
)
from posthog.temporal.data_imports.sources.stripe.custom import InvoiceListWithAllLines
from posthog.temporal.data_imports.sources.stripe.settings import APPEND_ONLY_INCREMENTAL_FIELDS

from products.data_warehouse.backend.models.external_table_definitions import get_dlt_mapping_for_external_table

LOGGER = get_logger(__name__)
DEFAULT_LIMIT = 100


def _tracked_stripe_http_client() -> RequestsClient:
    """Wrap a tracked `requests.Session` in Stripe's `RequestsClient` so every
    Stripe SDK call participates in our HTTP logging, metrics, and sample capture."""
    return RequestsClient(session=make_tracked_session())


def _clean_stripe_error_message(msg: str) -> str:
    """Collapse the long redacted middle of a restricted API key ('rk_live_********...****gbeftZ')
    so the error message stays short enough to render in a frontend toast. The prefix and
    suffix Stripe leaves visible are enough to identify the key in support escalations."""
    # Stripe redacts ~80 chars with `*`. Anything 5+ in a row is the redaction, never legitimate.
    return re.sub(r"\*{5,}", "***", msg)


def _call_stripe(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Invoke a Stripe SDK list method and rewrite any StripeError it raises with a cleaned
    message — primarily collapsing the long asterisk run from redacted restricted keys.

    Re-raises the same exception class (so framework-level non-retryable error matching on
    `"PermissionError"` etc. continues to work) but with a shorter, frontend-friendly message
    that still preserves the actionable detail Stripe surfaces (which scope is missing).
    """
    try:
        return method(*args, **kwargs)
    except stripe_lib.StripeError as e:
        cleaned = _clean_stripe_error_message(str(e))
        raise type(e)(message=cleaned) from e


def _stripe_base_addresses() -> BaseAddresses:
    # Redirect Stripe API calls to a local mock (e.g. STRIPE_API_BASE=http://localhost:12111)
    # when running the stripe-mock dev service. No-op in production where the var is unset.
    base = os.environ.get("STRIPE_API_BASE")
    return BaseAddresses(api=base) if base else BaseAddresses()


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
    parent_name: str = ""
    params: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class StripeResumeConfig:
    starting_after: str


def _build_resources(
    client: StripeClient, logger: Optional[FilteringBoundLogger] = None
) -> dict[str, Union[StripeResource, StripeNestedResource]]:
    """Single source of truth for the resources we sync from Stripe and how they relate.

    Used by both get_rows (for the actual sync) and validate_credentials (for permission
    checks). Nested resources carry their parent on `.parent`, so callers can derive the
    nested→parent linkage without restating it elsewhere.

    `logger` is only consumed by InvoiceListWithAllLines; pass None when the caller doesn't
    need the wrapped invoice expansion (e.g. validation, which just probes the list endpoint).
    """
    return {
        ACCOUNT_RESOURCE_NAME: StripeResource(method=client.accounts.list),
        BALANCE_TRANSACTION_RESOURCE_NAME: StripeResource(method=client.balance_transactions.list),
        CHARGE_RESOURCE_NAME: StripeResource(method=client.charges.list),
        CUSTOMER_RESOURCE_NAME: StripeResource(method=client.customers.list),
        DISPUTE_RESOURCE_NAME: StripeResource(method=client.disputes.list),
        INVOICE_ITEM_RESOURCE_NAME: StripeResource(method=client.invoice_items.list),
        INVOICE_RESOURCE_NAME: StripeResource(
            method=(
                (lambda params: InvoiceListWithAllLines(client, params, logger))  # type: ignore
                if logger is not None
                else client.invoices.list
            )
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
            parent_name=CUSTOMER_RESOURCE_NAME,
        ),
        CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME: StripeNestedResource(
            method=client.customers.payment_methods.list,
            nested_parent_param="customer",
            parent_id="id",
            parent=StripeResource(method=client.customers.list),
            parent_name=CUSTOMER_RESOURCE_NAME,
        ),
    }


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
    client = StripeClient(
        api_key,
        stripe_account=account_id,
        stripe_version="2024-09-30.acacia",
        max_network_retries=2,
        base_addresses=_stripe_base_addresses(),
        http_client=_tracked_stripe_http_client(),
    )
    default_params = {"limit": DEFAULT_LIMIT}
    resources = _build_resources(client, logger=logger)

    batcher = Batcher(logger=logger)

    resource = resources.get(endpoint, None)
    if not resource:
        raise Exception(f"Stripe endpoint does not exist: {endpoint}")

    logger.debug(f"Stripe: reading from resource {resource}")

    # Get the incremental field name for this endpoint
    incremental_field_config = APPEND_ONLY_INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else "created"

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

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
            stripe_parent_objects = _call_stripe(
                resource.parent.method,
                params={**default_params, **resource.parent.params, **resume_params},
            )
            for obj in stripe_parent_objects.auto_paging_iter():
                stripe_nested_objects = _call_stripe(
                    resource.method,
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

                        last_cur = py_table.column(resource.nested_parent_param)[-1].as_py()
                        resumable_source_manager.save_state(StripeResumeConfig(starting_after=last_cur))
        else:
            stripe_objects = _call_stripe(
                resource.method, params={**default_params, **resource.params, **resume_params}
            )
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

            if isinstance(resource, StripeNestedResource):
                last_cur = py_table.column(resource.nested_parent_param)[-1].as_py()
            else:
                last_cur = py_table.column("id")[-1].as_py()

            resumable_source_manager.save_state(StripeResumeConfig(starting_after=last_cur))

        return

    # check for any objects less than the minimum object we already have
    if db_incremental_field_earliest_value is not None:
        logger.debug(
            f"Stripe: iterating earliest objects from resource: created[lt] = {db_incremental_field_earliest_value}"
        )

        stripe_objects = _call_stripe(
            resource.method,
            params={
                **default_params,
                **resource.params,
                f"created[lt]": db_incremental_field_earliest_value,
            },
        )
        yield from stripe_objects.auto_paging_iter()

    # check for any objects more than the maximum object we already have
    if db_incremental_field_last_value is not None:
        logger.debug(f"Stripe: iterating latest objects from resource: created[gt] = {db_incremental_field_last_value}")

        stripe_objects = _call_stripe(
            resource.method,
            params={
                **default_params,
                **resource.params,
                f"created[gt]": db_incremental_field_last_value,
            },
        )
        for obj in stripe_objects.auto_paging_iter():
            if obj[incremental_field_name] <= db_incremental_field_last_value:
                break

            yield obj


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    data_col = table.column("data").to_pylist()
    created_col = table.column("created").to_pylist()

    # Deduplicate by object id, keeping the event with the latest created timestamp.
    # Multiple webhook events (e.g. customer.created then customer.updated) can reference
    # the same object, and delta merge doesn't deduplicate within the source batch.
    best_by_id: dict[str, tuple[int, dict]] = {}
    for data_str, event_created in zip(data_col, created_col):
        if data_str is None:
            continue
        obj = orjson.loads(data_str)["object"]
        obj_id = obj.get("id")
        if obj_id is None:
            continue

        ts = event_created if isinstance(event_created, int) else 0
        existing = best_by_id.get(obj_id)
        if existing is None or ts > existing[0]:
            best_by_id[obj_id] = (ts, obj)

    rows = [obj for _, obj in best_by_id.values()]
    return table_from_py_list(rows)


def stripe_source(
    api_key: str,
    account_id: Optional[str],
    endpoint: str,
    db_incremental_field_last_value: Optional[Any],
    db_incremental_field_earliest_value: Optional[Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StripeResumeConfig],
    webhook_source_manager: WebhookSourceManager,
    should_use_incremental_field: bool = False,
):
    column_mapping = get_dlt_mapping_for_external_table(f"stripe_{endpoint.lower()}")
    column_hints = {key: value.get("data_type") for key, value in column_mapping.items()}

    # Get the incremental field name for partition keys
    incremental_field_config = APPEND_ONLY_INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else "created"

    webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)()

    def items():
        if webhook_enabled:
            return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)

        return get_rows(
            api_key=api_key,
            account_id=account_id,
            endpoint=endpoint,
            db_incremental_field_last_value=db_incremental_field_last_value,
            db_incremental_field_earliest_value=db_incremental_field_earliest_value,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            resumable_source_manager=resumable_source_manager,
        )

    return SourceResponse(
        items=items,
        primary_keys=["id"],
        name=endpoint,
        column_hints=column_hints,
        # Stripe data is returned in descending timestamp order
        sort_mode="desc",
        partition_count=1,  # this enables partitioning
        partition_size=1,  # this enables partitioning
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[incremental_field_name],
    )


class StripePermissionError(Exception):
    """Raised when Stripe API key is valid but lacks read permission for one or more resources (403)."""

    def __init__(self, missing_permissions: dict[str, str]):
        self.missing_permissions = missing_permissions
        message = f"Stripe API key lacks permissions for: {', '.join(missing_permissions.keys())}"
        super().__init__(message)


class StripeAuthenticationError(Exception):
    """Raised when Stripe API key itself is invalid (401) — distinct from per-resource permission denial."""

    def __init__(self, stripe_message: str):
        self.stripe_message = stripe_message
        super().__init__(stripe_message)


class StripeValidationError(Exception):
    """Raised when one or more resources failed with a non-403 exception (network, schema, rate
    limit, etc.) during credential validation. Distinct from StripePermissionError so callers can
    decide whether to surface the verbose underlying message — permission errors are
    self-explanatory from the resource name, but unknown errors need the raw detail."""

    def __init__(self, errors: dict[str, str], missing_permissions: Optional[dict[str, str]] = None):
        self.errors = errors
        # If we also collected legitimate 403s before hitting the unknown error, keep them on the
        # exception so callers can report both classes of failure in a single message.
        self.missing_permissions = missing_permissions or {}
        message = f"Stripe validation failed for: {', '.join(errors.keys())}"
        super().__init__(message)


def validate_credentials(api_key: str, table_name: Optional[str] = None) -> bool:
    """
    Validates Stripe API credentials and checks permissions for all required resources.
    Returns True if the API key is valid and has all required permissions.
    Raises StripeAuthenticationError if the key is invalid/expired (401) — short-circuits the per-resource loop
    so the user does not see a misleading "lacks permissions for ALL resources" message.
    Raises StripePermissionError if the key is valid but lacks permissions for specific resources (403).
    """
    client = StripeClient(api_key, base_addresses=_stripe_base_addresses(), http_client=_tracked_stripe_http_client())

    # Drive validation off the same resource definitions get_rows uses — single source of truth.
    # Nested resources (e.g. /v1/customers/:id/payment_methods) can't be listed without a parent
    # ID, so we resolve them to their parent via the StripeNestedResource.parent_name field,
    # which names the top-level entry that gates the same scope.
    all_resources = _build_resources(client, logger=None)

    def _resolve_to_flat(name: str) -> tuple[str, StripeResource]:
        """Return (display_name, resource_to_probe) for a given table.

        For nested resources, the display name is `<nested> (<parent>)` — keeping the
        nested table the user toggled visible while making the actionable scope (the
        parent) explicit in the same string.
        """
        entry = all_resources[name]
        if isinstance(entry, StripeNestedResource):
            # Type narrowed via the CI test, not at runtime — see
            # test_validate_credentials_nested_resources_have_registered_parents.
            parent_entry = cast(StripeResource, all_resources[entry.parent_name])
            return f"{name} ({entry.parent_name})", parent_entry
        return name, entry

    missing_permissions: dict[str, str] = {}
    errors: dict[str, str] = {}

    if table_name is not None and table_name not in all_resources:
        raise StripePermissionError({table_name: f"{table_name} does not exist"})

    if table_name is not None:
        # Single-table validation: hit just that resource (or its parent for nested).
        display_name, flat_resource = _resolve_to_flat(table_name)
        resources_to_check = [(display_name, flat_resource)]
    else:
        # Full validation: probe every flat resource. Nested resources are covered by their
        # parent's check, so no need to enumerate them separately.
        resources_to_check = [
            (name, resource) for name, resource in all_resources.items() if isinstance(resource, StripeResource)
        ]

    for display_name, resource in resources_to_check:
        try:
            # Override params to limit=1 for cheap permission probing — we don't need real data.
            resource.method(params={"limit": 1})
        except stripe_lib.AuthenticationError as e:
            # 401 — key itself is bad; no point checking other resources, every call will 401 the same way.
            raise StripeAuthenticationError(_clean_stripe_error_message(str(e))) from e
        except stripe_lib.PermissionError as e:
            # 403 — this specific resource is not authorized for the key. The user_message is the
            # concise Stripe explanation; str(e) on a stripe error includes request id, status code,
            # and headers — way too noisy when the cause ("missing X read scope") is already obvious
            # from the resource name.
            raw = getattr(e, "user_message", None) or str(e)
            missing_permissions[display_name] = _clean_stripe_error_message(raw)
        except Exception as e:
            # Anything else (network, schema, rate limit, unexpected Stripe API change) is not a
            # permission problem — track separately so callers can render the verbose underlying
            # message instead of pretending it's a missing scope.
            errors[display_name] = _clean_stripe_error_message(str(e))

    # Errors take precedence over permission gaps because they indicate something went genuinely
    # wrong rather than a configuration issue the customer can self-serve. We still pass any
    # collected 403s along so the caller can report both in one message.
    if errors:
        raise StripeValidationError(errors, missing_permissions=missing_permissions)
    if missing_permissions:
        raise StripePermissionError(missing_permissions)

    return True


def create_webhook(api_key: str, stripe_account_id: str | None, webhook_url: str) -> WebhookCreationResult:
    logger = LOGGER.bind()

    hints = get_type_hints(WebhookEndpointService.CreateParams, include_extras=True)
    enabled_events_type = hints["enabled_events"]
    list_inner = get_args(enabled_events_type)[0]
    possible_event_values: tuple[str] = get_args(list_inner)

    prefixes_set = set(RESOURCE_TO_STRIPE_WEBHOOK_EVENT.values())
    filtered_events = [e for e in possible_event_values if any(e.startswith(f"{p}.") for p in prefixes_set)]

    if not filtered_events:
        return WebhookCreationResult(
            success=False,
            error="Could not determine valid webhook events. Please create the webhook manually.",
        )

    try:
        client = StripeClient(
            api_key,
            stripe_account=stripe_account_id,
            stripe_version="2024-09-30.acacia",
            max_network_retries=2,
            base_addresses=_stripe_base_addresses(),
            http_client=_tracked_stripe_http_client(),
        )

        endpoint = client.webhook_endpoints.create(
            params={
                "url": webhook_url,
                "enabled_events": filtered_events,  # type: ignore
                "description": "PostHog data warehouse webhook",
            }
        )

        extra_inputs: dict[str, Any] = {}
        if endpoint.secret:
            extra_inputs["signing_secret"] = endpoint.secret

        return WebhookCreationResult(success=True, extra_inputs=extra_inputs)
    except Exception as e:
        error_str = str(e)
        logger.warning(
            "Failed to create Stripe webhook",
            error=error_str,
        )

        if "permission" in error_str.lower() or "403" in error_str or "forbidden" in error_str.lower():
            return WebhookCreationResult(
                success=False,
                error="Your Stripe API key doesn't have permission to create webhooks. Please add the 'Write' permission for 'Webhook endpoints' to your API key, or create the webhook manually.",
            )

        return WebhookCreationResult(success=False, error=f"Failed to create webhook automatically: {error_str}")


def delete_webhook(api_key: str, stripe_account_id: str | None, webhook_url: str) -> WebhookDeletionResult:
    logger = LOGGER.bind()

    try:
        client = StripeClient(
            api_key,
            stripe_account=stripe_account_id,
            stripe_version="2024-09-30.acacia",
            max_network_retries=2,
            base_addresses=_stripe_base_addresses(),
            http_client=_tracked_stripe_http_client(),
        )

        endpoints = client.webhook_endpoints.list(params={"limit": 100})

        for endpoint in endpoints.auto_paging_iter():
            if endpoint.url == webhook_url:
                client.webhook_endpoints.delete(endpoint.id)
                return WebhookDeletionResult(success=True)

        return WebhookDeletionResult(success=True)
    except Exception as e:
        error_str = str(e)
        logger.warning(
            "Failed to delete Stripe webhook",
            error=error_str,
        )

        if "permission" in error_str.lower() or "403" in error_str or "forbidden" in error_str.lower():
            return WebhookDeletionResult(
                success=False,
                error="Your Stripe API key doesn't have permission to delete webhooks. Please delete the webhook manually from your Stripe dashboard.",
            )

        return WebhookDeletionResult(success=False, error=f"Failed to delete webhook: {error_str}")


def get_external_webhook_info(api_key: str, stripe_account_id: str | None, webhook_url: str) -> ExternalWebhookInfo:
    try:
        client = StripeClient(
            api_key,
            stripe_account=stripe_account_id,
            stripe_version="2024-09-30.acacia",
            max_network_retries=2,
            base_addresses=_stripe_base_addresses(),
            http_client=_tracked_stripe_http_client(),
        )

        endpoints = client.webhook_endpoints.list(params={"limit": 100})

        for endpoint in endpoints.auto_paging_iter():
            if endpoint.url == webhook_url:
                return ExternalWebhookInfo(
                    exists=True,
                    url=endpoint.url,
                    enabled_events=endpoint.enabled_events,
                    status=endpoint.status,
                    description=endpoint.description,
                    created_at=str(endpoint.created) if endpoint.created else None,
                )

        return ExternalWebhookInfo(exists=False)
    except Exception as e:
        error_str = str(e)
        if "permission" in error_str.lower() or "403" in error_str or "forbidden" in error_str.lower():
            return ExternalWebhookInfo(
                exists=False,
                error="Your Stripe API key doesn't have permission to read webhooks. Add the 'Read' permission for 'Webhook endpoints' to your API key.",
            )
        return ExternalWebhookInfo(exists=False, error=f"Failed to check webhook status: {error_str}")
