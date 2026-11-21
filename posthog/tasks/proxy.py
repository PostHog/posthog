import asyncio

from django.conf import settings
from django.db import DatabaseError

import requests
from celery import shared_task
from redis.exceptions import RedisError
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.service import RPCError

from posthog.exceptions_capture import capture_exception
from posthog.managed_proxy import cloudflare_proxy_lock, proxy_domain_can_be_provisioned, reconcile_cloudflare_proxy
from posthog.models import ProxyRecord
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue
from posthog.temporal.common.client import sync_connect
from posthog.temporal.proxy_service.cloudflare import CloudflareAPIError, update_cloudflare_proxy_root_redirect
from posthog.temporal.proxy_service.common import is_cloudflare_proxy, is_cloudflare_proxy_by_cname
from posthog.temporal.proxy_service.create import CreateManagedProxyInputs
from posthog.temporal.proxy_service.delete import DeleteManagedProxyInputs


def _resume_proxy_workflow(record: ProxyRecord) -> None:
    if record.status == ProxyRecord.Status.DELETING:
        workflow = "delete-proxy"
        workflow_id = f"proxy-delete-{record.id}"
        inputs: CreateManagedProxyInputs | DeleteManagedProxyInputs = DeleteManagedProxyInputs(
            organization_id=record.organization_id,
            proxy_record_id=record.id,
            domain=record.domain,
            target_cname=record.target_cname,
            root_redirect_url=record.root_redirect_url,
        )
    else:
        workflow = "create-proxy"
        workflow_id = f"proxy-create-{record.id}"
        inputs = CreateManagedProxyInputs(
            organization_id=record.organization_id,
            proxy_record_id=record.id,
            domain=record.domain,
            target_cname=record.target_cname,
        )
    temporal = sync_connect()
    # Stable IDs join running workflows while allowing a closed failed run to resume.
    asyncio.run(
        temporal.start_workflow(
            workflow,
            inputs,
            id=workflow_id,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
    )


def enqueue_proxy_reconciliation(organization_id: str, proxy_record_id: str) -> None:
    try:
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
    autoretry_for=(CloudflareAPIError, DatabaseError, requests.RequestException, RedisError, RPCError),
    retry_backoff=30,
    retry_backoff_max=3600,
    max_retries=10,
    acks_late=True,
    reject_on_worker_lost=True,
)
@skip_team_scope_audit
def reconcile_proxy(organization_id: str, proxy_record_id: str) -> None:
    with cloudflare_proxy_lock(proxy_record_id):
        record = ProxyRecord.objects.filter(
            organization_id=organization_id,
            pk=proxy_record_id,
            status__in=(ProxyRecord.Status.ISSUING, ProxyRecord.Status.ERRORING, ProxyRecord.Status.DELETING),
        ).first()
        if record is not None and record.status == ProxyRecord.Status.DELETING:
            _resume_proxy_workflow(record)
            return
        if record is not None and is_cloudflare_proxy(record):
            active = (
                ProxyRecord.objects.filter(organization_id=organization_id, pk=proxy_record_id)
                .exclude(organization__is_active=False)
                .exists()
            )
            if active:
                if proxy_domain_can_be_provisioned(record):
                    _resume_proxy_workflow(record)
                return
    reconcile_cloudflare_proxy(organization_id, proxy_record_id)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def reconcile_managed_proxies() -> None:
    for organization_id, proxy_record_id, target_cname, status in ProxyRecord.objects.values_list(
        "organization_id", "id", "target_cname", "status"
    ).iterator():
        if status == ProxyRecord.Status.DELETING or is_cloudflare_proxy_by_cname(target_cname):
            enqueue_proxy_reconciliation(str(organization_id), str(proxy_record_id))
