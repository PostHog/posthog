from django.db import DatabaseError

import requests
from celery import shared_task

from posthog.models import ProxyRecord
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue
from posthog.temporal.proxy_service.cloudflare import CloudflareAPIError, update_cloudflare_proxy_root_redirect


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(CloudflareAPIError, DatabaseError, requests.RequestException),
    retry_backoff=30,
    retry_backoff_max=3600,
    max_retries=10,
)
@skip_team_scope_audit
def reconcile_proxy_root_redirect(proxy_record_id: str) -> None:
    try:
        record = ProxyRecord.objects.get(id=proxy_record_id)
    except ProxyRecord.DoesNotExist:
        return

    update_cloudflare_proxy_root_redirect(record.domain, record.root_redirect_url)
