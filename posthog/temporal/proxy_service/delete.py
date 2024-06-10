from asgiref.sync import sync_to_async
from dataclasses import dataclass
import datetime as dt
import grpc.aio
import json
import uuid
from django.db import connection

from temporalio import activity, workflow
import temporalio.common

from posthog.models import ProxyRecord
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.common.logger import bind_temporal_org_worker_logger

from posthog.temporal.proxy_service.common import (
    get_grpc_client,
    NonRetriableException,
    update_proxy_record,
    UpdateProxyRecordInputs,
)
from posthog.temporal.proxy_service.proto import DeleteRequest


@dataclass
class DeleteProxyRecordInputs:
    organization_id: uuid.UUID
    proxy_record_id: uuid.UUID


@dataclass
class DeleteManagedProxyInputs:
    """Inputs for the DeleteManagedProxy Workflow and Activity."""

    organization_id: uuid.UUID
    proxy_record_id: uuid.UUID
    domain: str


@activity.defn
async def delete_proxy_record(inputs: DeleteProxyRecordInputs):
    """Activity that does a DNS lookup for the target subdomain and checks it has a CNAME
    record matching the expected value.
    """
    logger = await bind_temporal_org_worker_logger(organization_id=inputs.organization_id)
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
    logger = await bind_temporal_org_worker_logger(organization_id=inputs.organization_id)
    logger.info(
        "Deleting hosted proxy %s for domain %s",
        inputs.proxy_record_id,
        inputs.domain,
    )

    client = await get_grpc_client()

    try:
        await client.Delete(
            DeleteRequest(
                uuid=str(inputs.proxy_record_id),
                domain=inputs.domain,
            )
        )
    except grpc.aio.AioRpcError as e:
        if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
            raise NonRetriableException("invalid argument") from e
        if e.code() == grpc.StatusCode.NOT_FOUND:
            raise NonRetriableException("not found") from e
        raise


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
            # Call proxy provisioner to delete the HTTProxy and Certificate resources
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
                update_proxy_record,
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
