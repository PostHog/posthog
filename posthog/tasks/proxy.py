import random
import asyncio

from django.db import DatabaseError
from django.db.models import Q

import requests
from celery import shared_task
from redis.exceptions import RedisError
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.service import RPCError

from posthog.exceptions_capture import capture_exception
from posthog.managed_proxy import (
    cloudflare_proxy_lock,
    deprovision_cloudflare_proxy,
    proxy_domain_can_be_provisioned,
    restore_cloudflare_proxy,
)
from posthog.models import ProxyRecord
from posthog.models.proxy_record import CLOUDFLARE_DEPROVISIONED_STATES, CLOUDFLARE_RECOVERY_STATES
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue
from posthog.temporal.common.client import async_connect
from posthog.temporal.proxy_service.cloudflare import CloudflareAPIError, update_cloudflare_proxy_root_redirect
from posthog.temporal.proxy_service.common import is_cloudflare_proxy, is_cloudflare_proxy_by_cname
from posthog.temporal.proxy_service.create import CreateManagedProxyInputs, start_proxy_provisioning
from posthog.temporal.proxy_service.delete import start_proxy_deletion

PROXY_RECOVERY_TIMEOUT_SECONDS = 30
PROXY_SWEEP_SPREAD_SECONDS = 45 * 60


async def _resume_proxy(record: ProxyRecord) -> None:
    async with asyncio.timeout(PROXY_RECOVERY_TIMEOUT_SECONDS):
        temporal = await async_connect()
        if record.status == ProxyRecord.Status.DELETING:
            await start_proxy_deletion(temporal, record, id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING)
            return

        inputs = CreateManagedProxyInputs(
            organization_id=record.organization_id,
            proxy_record_id=record.id,
            domain=record.domain,
            target_cname=record.target_cname,
        )
        await start_proxy_provisioning(temporal, inputs, resume=True)


def enqueue_proxy_reconciliation(organization_id: str, proxy_record_id: str, *, countdown: int | None = None) -> None:
    try:
        if countdown is None:
            reconcile_proxy.delay(organization_id, proxy_record_id)
        else:
            reconcile_proxy.apply_async(args=(organization_id, proxy_record_id), countdown=countdown)
    except Exception as error:
        capture_exception(error, {"organization_id": organization_id, "proxy_record_id": proxy_record_id})


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(CloudflareAPIError, DatabaseError, requests.RequestException, RedisError),
    retry_backoff=30,
    retry_backoff_max=3600,
    max_retries=10,
)
@skip_team_scope_audit
def reconcile_proxy_root_redirect(proxy_record_id: str) -> None:
    with cloudflare_proxy_lock(proxy_record_id):
        record = (
            ProxyRecord.objects.filter(id=proxy_record_id)
            .exclude(organization__is_active=False)
            .exclude(organization__is_pending_deletion=True)
            .exclude(status=ProxyRecord.Status.DELETING)
            .first()
        )
        if record is None:
            return

        update_cloudflare_proxy_root_redirect(record.domain, record.root_redirect_url)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(CloudflareAPIError, DatabaseError, requests.RequestException, RedisError, RPCError, TimeoutError),
    retry_backoff=30,
    retry_backoff_max=3600,
    max_retries=10,
    acks_late=True,
    reject_on_worker_lost=True,
)
@skip_team_scope_audit
def reconcile_proxy(organization_id: str, proxy_record_id: str) -> None:
    with cloudflare_proxy_lock(proxy_record_id):
        record = (
            ProxyRecord.objects.select_related("organization")
            .filter(organization_id=organization_id, pk=proxy_record_id)
            .first()
        )
        if record is None:
            return

        cloudflare = is_cloudflare_proxy(record)
        inactive = record.organization.is_active is False
        if cloudflare and inactive:
            deprovision_cloudflare_proxy(record)
        if record.status == ProxyRecord.Status.DELETING:
            asyncio.run(_resume_proxy(record))
            return
        if inactive or record.organization.is_pending_deletion or not cloudflare:
            return

        recovering = record.cloudflare_activation_state in CLOUDFLARE_RECOVERY_STATES
        if not recovering and record.status != ProxyRecord.Status.ISSUING:
            return
        if not proxy_domain_can_be_provisioned(record):
            return
        if record.status in (ProxyRecord.Status.ISSUING, ProxyRecord.Status.ERRORING):
            asyncio.run(_resume_proxy(record))
        elif record.status in (ProxyRecord.Status.VALID, ProxyRecord.Status.WARNING):
            restore_cloudflare_proxy(record)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def reconcile_managed_proxies() -> None:
    pending = ProxyRecord.objects.filter(
        (Q(organization__is_active=False) & ~Q(cloudflare_activation_state__in=CLOUDFLARE_DEPROVISIONED_STATES))
        | Q(status=ProxyRecord.Status.DELETING)
        | (
            ~Q(organization__is_pending_deletion=True)
            & ~Q(organization__is_active=False)
            & (
                Q(status=ProxyRecord.Status.ISSUING)
                | (
                    Q(cloudflare_activation_state__in=CLOUDFLARE_RECOVERY_STATES)
                    & ~Q(status__in=(ProxyRecord.Status.WAITING, ProxyRecord.Status.TIMED_OUT))
                )
            )
        )
    )
    for organization_id, proxy_record_id, target_cname, status in pending.values_list(
        "organization_id", "id", "target_cname", "status"
    ).iterator():
        if status == ProxyRecord.Status.DELETING or is_cloudflare_proxy_by_cname(target_cname):
            enqueue_proxy_reconciliation(
                str(organization_id), str(proxy_record_id), countdown=random.randrange(PROXY_SWEEP_SPREAD_SECONDS)
            )
