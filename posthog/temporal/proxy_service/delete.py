import json
import uuid
import typing as t
import asyncio
import datetime as dt
from dataclasses import dataclass

from django.db import connection

import grpc.aio
import temporalio.common
from asgiref.sync import sync_to_async
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow

from posthog.models import ProxyRecord
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.proxy_service.cloudflare import (
    CloudflareAPIError,
    delete_custom_hostname,
    delete_worker_route,
    get_custom_hostname_by_domain,
    get_worker_route_by_pattern,
)
from posthog.temporal.proxy_service.common import (
    NonRetriableException,
    UpdateProxyRecordInputs,
    activity_update_proxy_record,
    get_grpc_client,
    is_cloudflare_proxy_record,
    use_gateway_api,
)
from posthog.temporal.proxy_service.proto import DeleteRequest

LOGGER = get_logger(__name__)


@dataclass
class DeleteProxyRecordInputs:
    organization_id: uuid.UUID
    proxy_record_id: uuid.UUID

    @property
    def properties_to_log(self) -> dict[str, t.Any]:
        return {
            "organization_id": self.organization_id,
            "proxy_record_id": self.proxy_record_id,
        }


@dataclass
class DeleteManagedProxyInputs:
    """Inputs for the DeleteManagedProxy Workflow and Activity."""

    organization_id: uuid.UUID
    proxy_record_id: uuid.UUID
    domain: str
    target_cname: str

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

    @sync_to_async
    def delete_record(proxy_record_id):
        connection.connect()
        pr = ProxyRecord.objects.get(id=proxy_record_id)
        pr.delete()

    await delete_record(inputs.proxy_record_id)


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
    """Activity that deletes Cloudflare Custom Hostname and Worker Route for a domain."""
    bind_contextvars(organization_id=inputs.organization_id)
    logger = LOGGER.bind()
    logger.info(
        "Deleting Cloudflare proxy resources for domain %s",
        inputs.domain,
    )

    errors: list[str] = []

    # Delete Worker Route first
    try:
        route = await asyncio.to_thread(get_worker_route_by_pattern, inputs.domain)
        if route:
            await asyncio.to_thread(delete_worker_route, route.id)
            logger.info("Deleted Cloudflare Worker Route %s for domain %s", route.id, inputs.domain)
        else:
            logger.info("No Cloudflare Worker Route found for domain %s", inputs.domain)
    except CloudflareAPIError as e:
        logger.warning("Failed to delete Cloudflare Worker Route for domain %s: %s", inputs.domain, e)
        errors.append(f"Worker Route deletion failed: {e}")

    # Delete Custom Hostname (attempt even if Worker Route deletion failed)
    try:
        hostname = await asyncio.to_thread(get_custom_hostname_by_domain, inputs.domain)
        if hostname:
            await asyncio.to_thread(delete_custom_hostname, hostname.id)
            logger.info("Deleted Cloudflare Custom Hostname %s for domain %s", hostname.id, inputs.domain)
        else:
            logger.info("No Cloudflare Custom Hostname found for domain %s", inputs.domain)
    except CloudflareAPIError as e:
        logger.warning("Failed to delete Cloudflare Custom Hostname for domain %s: %s", inputs.domain, e)
        errors.append(f"Custom Hostname deletion failed: {e}")

    if errors:
        raise NonRetriableException(f"Cloudflare API errors: {'; '.join(errors)}")


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
            # Use target_cname to determine which backend was used at creation
            if is_cloudflare_proxy_record(inputs.target_cname):
                # Delete Cloudflare Custom Hostname and Worker Route
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
