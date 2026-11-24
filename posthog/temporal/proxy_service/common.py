import uuid
import typing as t
import asyncio
from dataclasses import dataclass

from django.conf import settings
from django.db import connection
from django.utils import timezone

import grpc.aio
import posthoganalytics
from asgiref.sync import async_to_sync, sync_to_async
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.event_usage import groups
from posthog.models import ProxyRecord
from posthog.models.messaging import MessagingRecord
from posthog.models.organization import Organization
from posthog.models.proxy_record import CLOUDFLARE_RECOVERY_STATES
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.schedule import a_schedule_exists
from posthog.temporal.common.utils import close_stale_db_connections, on_asyncify_pool
from posthog.temporal.proxy_service.proto import ProxyProvisionerServiceStub

LOGGER = get_logger(__name__)
PROXY_MONITOR_LOOKUP_TIMEOUT_SECONDS = 15


async def get_grpc_client():
    channel = grpc.aio.insecure_channel(settings.PROXY_PROVISIONER_ADDR)
    await channel.channel_ready()
    return ProxyProvisionerServiceStub(channel)


def use_gateway_api() -> bool:
    """Returns whether to use Gateway API (Envoy Gateway) or Contour HTTPProxy."""
    return settings.PROXY_USE_GATEWAY_API


def use_cloudflare_proxy() -> bool:
    """Returns whether to use Cloudflare for SaaS for NEW proxy provisioning."""
    return settings.CLOUDFLARE_PROXY_ENABLED


def is_cloudflare_proxy_by_cname(target_cname: str) -> bool:
    """
    Determine if a proxy was created with Cloudflare based on its target_cname string.

    This is used to determine which system to use for monitoring and deletion,
    since proxies created before CLOUDFLARE_PROXY_ENABLED was turned on still
    exist in the legacy system and need to be handled accordingly.
    """
    cloudflare_base = settings.CLOUDFLARE_PROXY_BASE_CNAME
    if not cloudflare_base:
        return False
    # Strip trailing dot for comparison (DNS records may or may not have it)
    cloudflare_base = cloudflare_base.rstrip(".")
    target_cname = target_cname.rstrip(".")
    return target_cname.endswith(cloudflare_base)


def is_cloudflare_proxy(proxy_record: "ProxyRecord") -> bool:
    """
    Determine if a proxy was created with Cloudflare based on its target_cname.

    Convenience wrapper around is_cloudflare_proxy_by_cname for use with ProxyRecord objects.
    """
    return is_cloudflare_proxy_by_cname(proxy_record.target_cname)


class NonRetriableException(Exception):
    pass


class RecordDeletedException(NonRetriableException):
    pass


@sync_to_async
def get_record(proxy_record_id: uuid.UUID) -> t.Optional[ProxyRecord]:
    connection.connect()
    return ProxyRecord.objects.select_related("organization").filter(pk=proxy_record_id).first()


@sync_to_async
def record_exists(proxy_record_id: uuid.UUID) -> bool:
    connection.connect()
    pr = ProxyRecord.objects.filter(id=proxy_record_id)
    return len(pr) > 0


@on_asyncify_pool
def update_record(*, proxy_record_id: uuid.UUID, message: str | None = None, status: str | None = None) -> None:
    records = ProxyRecord.objects.filter(id=proxy_record_id).exclude(status=ProxyRecord.Status.DELETING)
    updates: dict[str, t.Any] = {"updated_at": timezone.now()}
    if message is not None:
        updates["message"] = message
    if status is not None:
        updates["status"] = status
    # A failed deletion and late provisioning updates must not erase deletion intent.
    # Keep this conditional in SQL so an API deletion cannot race a stale record save.
    if not records.update(**updates):
        raise RecordDeletedException("proxy record was deleted or marked for deletion before workflow completed")

    if status == ProxyRecord.Status.VALID:
        organization_id = (
            records.filter(cloudflare_activation_state__in=CLOUDFLARE_RECOVERY_STATES)
            .exclude(organization__is_active=False)
            .exclude(organization__is_pending_deletion=True)
            .values_list("organization_id", flat=True)
            .first()
        )
        if organization_id is not None:
            from posthog.tasks.proxy import enqueue_proxy_reconciliation  # noqa: PLC0415

            enqueue_proxy_reconciliation(str(organization_id), str(proxy_record_id))


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


@dataclass
class SendProxyCreatedEmailInputs:
    organization_id: uuid.UUID
    proxy_record_id: uuid.UUID
    domain: str

    @property
    def properties_to_log(self) -> dict[str, t.Any]:
        return {
            "organization_id": self.organization_id,
            "proxy_record_id": self.proxy_record_id,
            "domain": self.domain,
        }


@async_to_sync
async def _proxy_monitor_schedule_exists(proxy_record_id: uuid.UUID) -> bool:
    async with asyncio.timeout(PROXY_MONITOR_LOOKUP_TIMEOUT_SECONDS):
        temporal = await async_connect()
        return await a_schedule_exists(temporal, f"monitor-proxy-{proxy_record_id}")


@activity.defn
def activity_send_proxy_created_email(inputs: SendProxyCreatedEmailInputs):
    """Send an email notification when a reverse proxy has been successfully provisioned."""
    from posthog.email import EmailMessage, get_email_team_and_org_context, is_email_available

    if not is_email_available():
        return

    close_stale_db_connections()
    record = ProxyRecord.objects.select_related("created_by", "organization").filter(id=inputs.proxy_record_id).first()
    if record is None or record.created_by is None or not record.created_by.email:
        return

    campaign_key = f"proxy_provisioned_{inputs.proxy_record_id}"
    if MessagingRecord.objects.filter(campaign_key=campaign_key, sent_at__isnull=False).exists():
        return

    # A monitor schedule is created after the first successful provisioning, even if email was unavailable.
    if _proxy_monitor_schedule_exists(inputs.proxy_record_id):
        return

    try:
        user = record.created_by
        message = EmailMessage(
            campaign_key=campaign_key,
            subject="Your PostHog reverse proxy is ready",
            template_name="proxy_provisioned",
            template_context={
                "user_name": user.first_name,
                "domain": inputs.domain,
                "settings_url": f"{settings.SITE_URL}/settings/organization-proxy",
                **get_email_team_and_org_context(organization=record.organization),
            },
            use_http=True,
        )
        message.add_user_recipient(user)
        message.send(send_async=True)
    except Exception:
        LOGGER.warning(
            "Failed to send proxy provisioned email for proxy %s",
            inputs.proxy_record_id,
            exc_info=True,
        )
