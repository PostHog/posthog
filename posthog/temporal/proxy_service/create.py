from dataclasses import dataclass
import datetime as dt
import grpc.aio
import dns.resolver
import uuid
from django.conf import settings


from temporalio import activity, workflow
import temporalio.common

from posthog.models import ProxyRecord
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.common.logger import bind_temporal_org_worker_logger

from posthog.temporal.proxy_service.proto import CreateRequest, StatusRequest, ProxyProvisionerServiceStub


class NonRetriableException(Exception):
    pass


@dataclass
class CreateHostedProxyInputs:
    """Inputs for the CreateHostedProxy Workflow and Activity."""

    organization_id: uuid.UUID
    proxy_record_id: uuid.UUID
    domain: str
    target_cname: str


@dataclass
class UpdateProxyRecordInputs:
    organization_id: uuid.UUID
    proxy_record_id: uuid.UUID
    status: ProxyRecord.Status


@dataclass
class WaitForDNSRecordsInputs:
    organization_id: uuid.UUID
    domain: str
    target_cname: str


@dataclass
class WaitForCertificateInputs:
    organization_id: uuid.UUID
    proxy_record_id: uuid.UUID
    domain: str


async def get_grpc_client():
    channel = grpc.aio.insecure_channel(settings.PROXY_PROVISIONER_ADDR)
    await channel.channel_ready()
    return ProxyProvisionerServiceStub(channel)


@activity.defn
async def update_proxy_record(inputs: UpdateProxyRecordInputs):
    """Activity that does a DNS lookup for the target subdomain and checks it has a CNAME
    record matching the expected value.
    """
    logger = await bind_temporal_org_worker_logger(organization_id=inputs.organization_id)
    logger.info(
        "Updating proxy record %s state to %s",
        inputs.proxy_record_id,
        inputs.status,
    )

    pr = ProxyRecord.objects.get(id=inputs.proxy_record_id)
    pr.status = inputs.status
    pr.save()


@activity.defn
async def wait_for_dns_records(inputs: WaitForDNSRecordsInputs):
    """Activity that does a DNS lookup for the target subdomain and checks it has a CNAME
    record matching the expected value.
    """
    logger = await bind_temporal_org_worker_logger(organization_id=inputs.organization_id)
    logger.info(
        "Looking up DNS record for %s, expecting %s",
        inputs.domain,
        inputs.target_cname,
    )

    try:
        cnames = dns.resolver.query(inputs.domain, "CNAME")
        value = cnames[0].target.canonicalize().to_text()

        if value == inputs.target_cname:
            return
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        # retriable
        raise
    except Exception as e:
        raise NonRetriableException("unknown exception in check_dns_record") from e


@activity.defn
async def create_hosted_proxy(inputs: CreateHostedProxyInputs):
    """Activity that calls the proxy provisioner to create the resources for
    a Hosted Proxy. It also waits for provisioning to be complete and updates
    the Proxy Record's state as it goes.
    """
    logger = await bind_temporal_org_worker_logger(organization_id=inputs.organization_id)
    logger.info(
        "Creating hosted proxy for domain %s",
        inputs.domain,
    )

    client = get_grpc_client()

    try:
        await client.Create(
            CreateRequest(
                uuid=str(inputs.proxy_record_id),
                domain=inputs.domain,
            )
        )
    except grpc.aio.AioRpcError as e:
        if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
            raise NonRetriableException("invalid argument") from e


@activity.defn
async def wait_for_certificate(inputs: WaitForCertificateInputs):
    """Activity that calls the proxy provisioner to create the resources for
    a Hosted Proxy. It also waits for provisioning to be complete and updates
    the Proxy Record's state as it goes.
    """
    logger = await bind_temporal_org_worker_logger(organization_id=inputs.organization_id)
    logger.info(
        "Creating hosted proxy for domain %s",
        inputs.domain,
    )

    client = get_grpc_client()

    try:
        response = await client.Status(
            StatusRequest(
                uuid=str(inputs.proxy_record_id),
                domain=inputs.domain,
            )
        )

        # throw exceptions until ready
        # this lets temporal handle retry/backoff logic
        if response.certificateStatus != "READY":
            raise Exception("certificate not yet ready")
    except grpc.aio.AioRpcError as e:
        if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
            raise NonRetriableException("invalid argument") from e
        if e.code() == grpc.StatusCode.NOT_FOUND:
            raise NonRetriableException("not found") from e


@workflow.defn(name="create-proxy")
class CreateHostedProxyWorkflow(PostHogWorkflow):
    """A Temporal Workflow to create a Hosted Reverse Proxy."""

    @temporalio.workflow.run
    async def run(self, inputs: CreateHostedProxyInputs) -> None:
        """Workflow implementation to create a Hosted Reverse Proxy."""

        try:
            # Wait for DNS record to be created.
            # This will fail and retry infinitely until the expected resolution is found.
            # Timeout after 7 days - users will need to delete and recreate after this time.
            await temporalio.workflow.execute_activity(
                wait_for_dns_records,
                WaitForDNSRecordsInputs(
                    organization_id=inputs.organization_id, domain=inputs.domain, target_cname=inputs.target_cname
                ),
                schedule_to_close_timeout=dt.timedelta(days=7),
                start_to_close_timeout=dt.timedelta(seconds=2),
                retry_policy=temporalio.common.RetryPolicy(
                    backoff_coefficient=1.1,
                    initial_interval=dt.timedelta(seconds=3),
                    maximum_interval=dt.timedelta(seconds=3600),
                    maximum_attempts=0,
                    non_retryable_error_types=["NonRetriableException"],
                ),
            )

            # We've found the correct DNS record - update record to the ISSUING state
            await temporalio.workflow.execute_activity(
                update_proxy_record,
                UpdateProxyRecordInputs(
                    organization_id=inputs.organization_id,
                    proxy_record_id=inputs.proxy_record_id,
                    status=ProxyRecord.Status.ISSUING,
                ),
                start_to_close_timeout=dt.timedelta(seconds=10),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=2,
                ),
            )

            # Call proxy provisioner to create the HTTProxy and Certificate resources
            await temporalio.workflow.execute_activity(
                create_hosted_proxy,
                inputs,
                schedule_to_close_timeout=dt.timedelta(minutes=5),
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_attempts=5,
                    non_retryable_error_types=["NonRetriableException"],
                ),
            )

            # Waits for the certificate to be provisioned and for the proxy to be live
            await temporalio.workflow.execute_activity(
                wait_for_certificate,
                WaitForCertificateInputs(
                    organization_id=inputs.organization_id,
                    proxy_record_id=inputs.proxy_record_id,
                    domain=inputs.domain,
                ),
                schedule_to_close_timeout=dt.timedelta(minutes=15),
                start_to_close_timeout=dt.timedelta(seconds=5),
                retry_policy=temporalio.common.RetryPolicy(
                    backoff_coefficient=1.1,
                    initial_interval=dt.timedelta(seconds=1),
                    maximum_interval=dt.timedelta(seconds=10),
                    maximum_attempts=0,
                    non_retryable_error_types=["NonRetriableException"],
                ),
            )

            # Everything's created and ready to go, update to VALID
            await temporalio.workflow.execute_activity(
                update_proxy_record,
                UpdateProxyRecordInputs(
                    organization_id=inputs.organization_id,
                    proxy_record_id=inputs.proxy_record_id,
                    status=ProxyRecord.Status.VALID,
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
                    status=ProxyRecord.Status.ERRORING,
                ),
                start_to_close_timeout=dt.timedelta(seconds=60),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=10,
                ),
            )
            raise
