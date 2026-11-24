import random
import asyncio

from django.conf import settings
from django.db import DatabaseError
from django.db.models import Q

import requests
from celery import shared_task
from redis.exceptions import RedisError
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.service import RPCError

from posthog.exceptions_capture import capture_exception
from posthog.managed_proxy import cloudflare_proxy_lock, proxy_domain_can_be_provisioned, reconcile_cloudflare_proxy
from posthog.models import ProxyRecord
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue
from posthog.temporal.common.client import async_connect
from posthog.temporal.proxy_service.cloudflare import CloudflareAPIError, update_cloudflare_proxy_root_redirect
from posthog.temporal.proxy_service.common import is_cloudflare_proxy, is_cloudflare_proxy_by_cname
from posthog.temporal.proxy_service.create import CreateManagedProxyInputs, start_proxy_provisioning
from posthog.temporal.proxy_service.delete import DeleteManagedProxyInputs

PROXY_RECOVERY_TIMEOUT_SECONDS = 30
PROXY_SWEEP_SPREAD_SECONDS = 45 * 60


async def _resume_proxy_deletion(record: ProxyRecord, temporal: Client) -> None:
    inputs = DeleteManagedProxyInputs(
        organization_id=record.organization_id,
        proxy_record_id=record.id,
        domain=record.domain,
        target_cname=record.target_cname,
        root_redirect_url=record.root_redirect_url,
    )
    await temporal.start_workflow(
        "delete-proxy",
        inputs,
        id=f"proxy-delete-{record.id}",
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )


async def _resume_proxy(record: ProxyRecord) -> None:
    async with asyncio.timeout(PROXY_RECOVERY_TIMEOUT_SECONDS):
        temporal = await async_connect()
        if record.status == ProxyRecord.Status.DELETING:
            await _resume_proxy_deletion(record, temporal)
            return

        inputs = CreateManagedProxyInputs(
            organization_id=record.organization_id,
            proxy_record_id=record.id,
            domain=record.domain,
            target_cname=record.target_cname,
        )
        await start_proxy_provisioning(temporal, inputs, resume=True)


def enqueue_proxy_reconciliation(organization_id: str, proxy_record_id: str, *, from_sweep: bool = False) -> None:
    try:
        if from_sweep:
            reconcile_proxy.apply_async(
                args=(organization_id, proxy_record_id),
                kwargs={"from_sweep": True},
                countdown=random.randrange(PROXY_SWEEP_SPREAD_SECONDS),
            )
        else:
            reconcile_proxy.delay(organization_id, proxy_record_id)
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
def reconcile_proxy(organization_id: str, proxy_record_id: str, *, from_sweep: bool = False) -> None:
    with cloudflare_proxy_lock(proxy_record_id):
        record = ProxyRecord.objects.filter(
            organization_id=organization_id,
            pk=proxy_record_id,
            status__in=(ProxyRecord.Status.ISSUING, ProxyRecord.Status.ERRORING, ProxyRecord.Status.DELETING),
        ).first()
        if record is not None and record.status == ProxyRecord.Status.DELETING:
            asyncio.run(_resume_proxy(record))
            return
        if record is not None and is_cloudflare_proxy(record):
            active = (
                ProxyRecord.objects.filter(organization_id=organization_id, pk=proxy_record_id)
                .exclude(organization__is_active=False)
                .exists()
            )
            if active:
                if from_sweep and record.status == ProxyRecord.Status.ERRORING and not record.needs_activation_recovery:
                    return
                if proxy_domain_can_be_provisioned(record):
                    asyncio.run(_resume_proxy(record))
                return
    reconcile_cloudflare_proxy(organization_id, proxy_record_id, from_sweep=from_sweep)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def reconcile_managed_proxies() -> None:
    pending = ProxyRecord.objects.filter(
        Q(organization__is_active=False, cloudflare_deprovisioned=False)
        | Q(status=ProxyRecord.Status.DELETING)
        | (
            ~Q(organization__is_active=False)
            & (
                Q(status=ProxyRecord.Status.ISSUING)
                | (
                    Q(needs_activation_recovery=True)
                    & ~Q(status__in=(ProxyRecord.Status.WAITING, ProxyRecord.Status.TIMED_OUT))
                )
            )
        )
    )
    for organization_id, proxy_record_id, target_cname, status in pending.values_list(
        "organization_id", "id", "target_cname", "status"
    ).iterator():
        if status == ProxyRecord.Status.DELETING or is_cloudflare_proxy_by_cname(target_cname):
            enqueue_proxy_reconciliation(str(organization_id), str(proxy_record_id), from_sweep=True)
