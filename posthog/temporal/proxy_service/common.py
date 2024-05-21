from dataclasses import dataclass
import grpc.aio
import uuid
from django.conf import settings

from temporalio import activity

from posthog.models import ProxyRecord
from posthog.temporal.common.logger import bind_temporal_org_worker_logger

from posthog.temporal.proxy_service.proto import ProxyProvisionerServiceStub


async def get_grpc_client():
    channel = grpc.aio.insecure_channel(settings.PROXY_PROVISIONER_ADDR)
    await channel.channel_ready()
    return ProxyProvisionerServiceStub(channel)


class NonRetriableException(Exception):
    pass


@dataclass
class UpdateProxyRecordInputs:
    organization_id: uuid.UUID
    proxy_record_id: uuid.UUID
    status: ProxyRecord.Status


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
