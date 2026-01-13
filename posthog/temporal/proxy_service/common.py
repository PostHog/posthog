import uuid
import typing as t
from dataclasses import dataclass

from django.conf import settings
from django.db import connection

import grpc.aio
import posthoganalytics
from asgiref.sync import sync_to_async
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.event_usage import groups
from posthog.models import ProxyRecord
from posthog.models.organization import Organization
from posthog.temporal.common.logger import get_logger
from posthog.temporal.proxy_service.proto import ProxyProvisionerServiceStub

LOGGER = get_logger(__name__)


async def get_grpc_client():
    channel = grpc.aio.insecure_channel(settings.PROXY_PROVISIONER_ADDR)
    await channel.channel_ready()
    return ProxyProvisionerServiceStub(channel)


def use_gateway_api() -> bool:
    """Returns whether to use Gateway API (Envoy Gateway) or Contour HTTPProxy."""
    return settings.PROXY_USE_GATEWAY_API


def use_cloudflare_proxy(organization_id: uuid.UUID | None = None) -> bool:
    """Returns whether to use Cloudflare for SaaS for proxy provisioning.

    If organization_id is provided, checks the feature flag for that org.
    Otherwise falls back to the global CLOUDFLARE_PROXY_ENABLED setting.
    """
    # Global kill switch - if not enabled at instance level, never use Cloudflare
    if not settings.CLOUDFLARE_PROXY_ENABLED:
        return False

    # If no org_id provided, cannot determine org-specific flag, return False for safety
    if organization_id is None:
        return False

    # Check feature flag for this specific organization
    return posthoganalytics.feature_enabled(
        "managed-proxy-use-cloudflare",
        f"org-{organization_id}",
        groups={"organization": str(organization_id)},
        group_properties={"organization": {"id": str(organization_id)}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


def is_cloudflare_proxy_record(target_cname: str) -> bool:
    """Check if a proxy record was created with Cloudflare based on its target_cname.

    This is used by delete/monitor operations to determine which backend to use,
    rather than re-evaluating the feature flag which may have changed since creation.
    """
    return settings.CLOUDFLARE_PROXY_BASE_CNAME and settings.CLOUDFLARE_PROXY_BASE_CNAME in target_cname


class NonRetriableException(Exception):
    pass


class RecordDeletedException(NonRetriableException):
    pass


@sync_to_async
def get_record(proxy_record_id: uuid.UUID) -> t.Optional[ProxyRecord]:
    connection.connect()
    pr = ProxyRecord.objects.filter(id=proxy_record_id)
    return pr.first()


@sync_to_async
def record_exists(proxy_record_id: uuid.UUID) -> bool:
    connection.connect()
    pr = ProxyRecord.objects.filter(id=proxy_record_id)
    return len(pr) > 0


@sync_to_async
def update_record(*, proxy_record_id: uuid.UUID, message: t.Optional[str] = None, status: t.Optional[str] = None):
    connection.connect()
    prs = ProxyRecord.objects.filter(id=proxy_record_id)
    if len(prs) == 0:
        raise RecordDeletedException("proxy record was deleted before workflow completed")
    pr = prs[0]
    if message is not None:
        pr.message = message
    if status is not None:
        pr.status = status
    pr.save()


@dataclass
class UpdateProxyRecordInputs:
    organization_id: uuid.UUID
    proxy_record_id: uuid.UUID
    status: str
    message: t.Optional[str]

    def __init__(
        self, organization_id: uuid.UUID, proxy_record_id: uuid.UUID, status: str, message: t.Optional[str] = None
    ):
        self.organization_id = organization_id
        self.proxy_record_id = proxy_record_id
        self.status = status
        self.message = message

    @property
    def properties_to_log(self) -> dict[str, t.Any]:
        return {
            "organization_id": self.organization_id,
            "proxy_record_id": self.proxy_record_id,
            "status": self.status,
            "message": self.message,
        }


@activity.defn
async def activity_update_proxy_record(inputs: UpdateProxyRecordInputs):
    """Activity that does a DNS lookup for the target subdomain and checks it has a CNAME
    record matching the expected value.
    """
    bind_contextvars(organization_id=inputs.organization_id)
    logger = LOGGER.bind()
    logger.info(
        "Updating proxy record %s state to %s with message %s",
        inputs.proxy_record_id,
        inputs.status,
        inputs.message,
    )

    await update_record(proxy_record_id=inputs.proxy_record_id, status=inputs.status, message=inputs.message)


@dataclass
class CaptureEventInputs:
    organization_id: uuid.UUID
    proxy_record_id: uuid.UUID
    event_type: str
    properties: dict[str, t.Any]

    def __init__(
        self, *, organization_id: uuid.UUID, proxy_record_id: uuid.UUID, event_type: str, properties: dict[str, t.Any]
    ):
        self.organization_id = organization_id
        self.proxy_record_id = proxy_record_id
        self.event_type = event_type
        self.properties = properties

    @property
    def properties_to_log(self) -> dict[str, t.Any]:
        return {
            "organization_id": self.organization_id,
            "proxy_record_id": self.proxy_record_id,
            "event_type": self.event_type,
            "properties": self.properties,
        }


@activity.defn
def activity_capture_event(inputs: CaptureEventInputs):
    connection.connect()
    record = ProxyRecord.objects.filter(id=inputs.proxy_record_id).first()
    if record is None:
        return
    org = Organization.objects.get(id=inputs.organization_id)

    posthoganalytics.capture(
        event=f"managed reverse proxy {inputs.event_type}",
        distinct_id=f"org-{record.organization_id}",
        properties={
            "organization_id": record.organization_id,
            "proxy_record_id": inputs.proxy_record_id,
            "domain": record.domain if record else None,
            "target_cname": record.target_cname if record else None,
            **inputs.properties,
        },
        groups=groups(org),
    )
