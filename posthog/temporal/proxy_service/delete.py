import json
import uuid
import typing as t
import datetime as dt

from django.db import connection

import grpc.aio
import temporalio.common
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow

from posthog.dataclasses import frozen
from posthog.models import ProxyRecord
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import on_asyncify_pool
from posthog.temporal.proxy_service.cloudflare import (
    CloudflareAPIError,
    delete_custom_hostname,
    get_custom_hostname_by_domain,
    update_cloudflare_proxy_root_redirect,
)
from posthog.temporal.proxy_service.common import (
    NonRetriableException,
    UpdateProxyRecordInputs,
    activity_update_proxy_record,
    get_grpc_client,
    is_cloudflare_proxy_by_cname,
    use_gateway_api,
)
from posthog.temporal.proxy_service.proto import DeleteRequest

LOGGER = get_logger(__name__)


@frozen
class DeleteProxyRecordInputs:
    organization_id: uuid.UUID
    proxy_record_id: uuid.UUID

    @property
    def properties_to_log(self) -> dict[str, t.Any]:
        return {
            "organization_id": self.organization_id,
            "proxy_record_id": self.proxy_record_id,
        }


@frozen
class DeleteManagedProxyInputs:
    """Inputs for the DeleteManagedProxy Workflow and Activity."""

    organization_id: uuid.UUID
    proxy_record_id: uuid.UUID
    domain: str
    target_cname: str = ""  # Used to determine if proxy is Cloudflare or legacy
    root_redirect_url: str | None = None

    @property
    def properties_to_log(self) -> dict[str, t.Any]:
        return {
            "organization_id": self.organization_id,
            "proxy_record_id": self.proxy_record_id,
            "domain": self.domain,
            "target_cname": self.target_cname,
        }


@activity.defn
async def delete_proxy_record(inputs: DeleteProxyRecordInputs):
    """Activity that does a DNS lookup for the target subdomain and checks it has a CNAME
    record matching the expected value.
    """
    bind_contextvars(organization_id=inputs.organization_id)
    logger = LOGGER.bind()

    logger.info(
        "Deleting proxy record %s",
        inputs.proxy_record_id,
    )

    def delete_record() -> None:
        from posthog.managed_proxy import cloudflare_proxy_lock  # noqa: PLC0415

        with cloudflare_proxy_lock(inputs.proxy_record_id):
            connection.connect()
            ProxyRecord.objects.filter(organization_id=inputs.organization_id, pk=inputs.proxy_record_id).delete()

    await on_asyncify_pool(delete_record)()


@activity.defn
async def delete_managed_proxy(inputs: DeleteManagedProxyInputs):
    """Activity that calls the proxy provisioner to delete the resources for a Hosted Proxy."""
    bind_contextvars(organization_id=inputs.organization_id)
    logger = LOGGER.bind()
    logger.info(
        "Deleting hosted proxy %s for domain %s",
        inputs.proxy_record_id,
        inputs.domain,
    )

    client = await get_grpc_client()

    # Use Gateway API (Envoy Gateway) for dev environment, Contour for others
    use_gateway = use_gateway_api()

    logger.info(
        "Deleting proxy with use_gateway_api=%s for domain %s",
        use_gateway,
        inputs.domain,
    )

    try:
        await client.Delete(
            DeleteRequest(
                uuid=str(inputs.proxy_record_id),
                domain=inputs.domain,
                use_gateway_api=use_gateway,
            )
        )
    except grpc.aio.AioRpcError as e:
        if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
            raise NonRetriableException("invalid argument") from e
        if e.code() == grpc.StatusCode.NOT_FOUND:
            raise NonRetriableException("not found") from e
        raise


@activity.defn
async def delete_cloudflare_proxy(inputs: DeleteManagedProxyInputs):
    """Activity that deletes Cloudflare Custom Hostname for a domain."""
    bind_contextvars(organization_id=inputs.organization_id)
    logger = LOGGER.bind()
    logger.info(
        "Deleting Cloudflare proxy resources for domain %s",
        inputs.domain,
    )

    def delete_resources() -> None:
        from posthog.managed_proxy import cloudflare_proxy_lock  # noqa: PLC0415

        with cloudflare_proxy_lock(inputs.proxy_record_id):
            errors: list[str] = []

            # Worker route cleanup intentionally omitted: per-domain routes are no longer created (we
            # now rely on a single wildcard */* route). Proxies created before this change may have
            # orphaned per-domain routes; those should be cleaned up via a separate migration script.
            # Delete Custom Hostname
            try:
                hostname = get_custom_hostname_by_domain(inputs.domain)
                if hostname:
                    delete_custom_hostname(hostname.id)
                    logger.info("Deleted Cloudflare Custom Hostname %s for domain %s", hostname.id, inputs.domain)
                else:
                    logger.info("No Cloudflare Custom Hostname found for domain %s", inputs.domain)
            except CloudflareAPIError as e:
                logger.warning("Failed to delete Cloudflare Custom Hostname for domain %s: %s", inputs.domain, e)
                errors.append(f"Custom Hostname deletion failed: {e}")

            try:
                update_cloudflare_proxy_root_redirect(inputs.domain, None)
            except CloudflareAPIError as e:
                logger.warning("Failed to delete root redirect for domain %s: %s", inputs.domain, e)
                errors.append(f"Root redirect deletion failed: {e}")

            if errors:
                raise NonRetriableException(f"Cloudflare API errors: {'; '.join(errors)}")

    await on_asyncify_pool(delete_resources)()


@workflow.defn(name="delete-proxy")
class DeleteManagedProxyWorkflow(PostHogWorkflow):
    """A Temporal Workflow to delete a Managed reverse Proxy."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> DeleteManagedProxyInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return DeleteManagedProxyInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: DeleteManagedProxyInputs) -> None:
        """Workflow implementation to delete a Managed reverse Proxy."""

        try:
            # Branch based on how the proxy was created (detected from target_cname),
            # not the global flag, since legacy proxies need legacy deletion
            if inputs.target_cname and is_cloudflare_proxy_by_cname(inputs.target_cname):
                # Delete Cloudflare Custom Hostname
                await temporalio.workflow.execute_activity(
                    delete_cloudflare_proxy,
                    inputs,
                    schedule_to_close_timeout=dt.timedelta(minutes=5),
                    start_to_close_timeout=dt.timedelta(minutes=1),
                    retry_policy=temporalio.common.RetryPolicy(
                        initial_interval=dt.timedelta(seconds=10),
                        maximum_attempts=5,
                        non_retryable_error_types=["NonRetriableException"],
                    ),
                )
            else:
                # Legacy path: Call proxy provisioner to delete the HTTPProxy and Certificate resources
                await temporalio.workflow.execute_activity(
                    delete_managed_proxy,
                    inputs,
                    schedule_to_close_timeout=dt.timedelta(minutes=5),
                    start_to_close_timeout=dt.timedelta(minutes=1),
                    retry_policy=temporalio.common.RetryPolicy(
                        initial_interval=dt.timedelta(seconds=10),
                        maximum_attempts=5,
                        non_retryable_error_types=["NonRetriableException"],
                    ),
                )

            # Resources have been deleted - delete the proxy record.
            await temporalio.workflow.execute_activity(
                delete_proxy_record,
                DeleteProxyRecordInputs(
                    organization_id=inputs.organization_id,
                    proxy_record_id=inputs.proxy_record_id,
                ),
                start_to_close_timeout=dt.timedelta(seconds=10),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=2,
                ),
            )

        except Exception:
            # Something went wrong - set the record to error state
            await temporalio.workflow.execute_activity(
                activity_update_proxy_record,
                UpdateProxyRecordInputs(
                    organization_id=inputs.organization_id,
                    proxy_record_id=inputs.proxy_record_id,
                    status=ProxyRecord.Status.ERRORING.value,
                ),
                start_to_close_timeout=dt.timedelta(seconds=60),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=10,
                ),
            )
            raise
