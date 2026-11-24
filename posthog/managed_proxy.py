from uuid import UUID

from redis.lock import Lock

from posthog.cloud_utils import is_cloud
from posthog.models import ProxyRecord
from posthog.models.proxy_record import is_reserved_proxy_domain, org_may_register_reserved_domain
from posthog.redis import get_client
from posthog.security.oob_domains import matched_oob_domain
from posthog.temporal.proxy_service.cloudflare import (
    CloudflareAPIError,
    create_custom_hostname,
    delete_custom_hostname,
    get_custom_hostname_by_domain,
    update_cloudflare_proxy_root_redirect,
)
from posthog.temporal.proxy_service.common import is_cloudflare_proxy


def cloudflare_proxy_lock(proxy_record_id: str | UUID) -> Lock:
    proxy_record_id = UUID(str(proxy_record_id))
    return get_client().lock(f"managed-proxy-reconcile:{proxy_record_id}", timeout=180, blocking_timeout=5)


def proxy_domain_can_be_provisioned(record: ProxyRecord) -> bool:
    if is_cloud() and matched_oob_domain(record.domain):
        return False
    return not is_reserved_proxy_domain(record.domain) or org_may_register_reserved_domain(
        record.organization_id, record.domain
    )


def _restore_cloudflare_proxy(record: ProxyRecord) -> None:
    if record.cloudflare_deprovisioned:
        ProxyRecord.objects.filter(pk=record.pk).update(cloudflare_deprovisioned=False)
    hostname = get_custom_hostname_by_domain(record.domain)
    if hostname is None:
        try:
            create_custom_hostname(record.domain)
        except CloudflareAPIError as error:
            if not any(item.get("code") == 1406 for item in error.errors):
                raise
    if record.root_redirect_url:
        update_cloudflare_proxy_root_redirect(record.domain, record.root_redirect_url)


def _deprovision_cloudflare_proxy(record: ProxyRecord) -> None:
    if record.cloudflare_deprovisioned:
        return
    hostname = get_custom_hostname_by_domain(record.domain)
    needs_recovery = record.status in (
        ProxyRecord.Status.ISSUING,
        ProxyRecord.Status.VALID,
        ProxyRecord.Status.WARNING,
    ) or (record.status == ProxyRecord.Status.ERRORING and hostname is not None)
    # Record the intent first so a partial Cloudflare cleanup can still be recovered.
    if needs_recovery and not record.needs_activation_recovery:
        ProxyRecord.objects.filter(pk=record.pk).update(needs_activation_recovery=True)
    if hostname:
        delete_custom_hostname(hostname.id)
    update_cloudflare_proxy_root_redirect(record.domain, None)
    ProxyRecord.objects.filter(pk=record.pk).update(cloudflare_deprovisioned=True)


def reconcile_cloudflare_proxy(
    organization_id: str | UUID, proxy_record_id: str | UUID, *, from_sweep: bool = False
) -> bool:
    with cloudflare_proxy_lock(proxy_record_id):
        record = ProxyRecord.objects.filter(organization_id=organization_id, pk=proxy_record_id).first()
        if record is None or not is_cloudflare_proxy(record):
            return False

        active = (
            ProxyRecord.objects.filter(organization_id=organization_id, pk=record.pk)
            .exclude(organization__is_active=False)
            .exists()
        )
        if active:
            if from_sweep and not record.needs_activation_recovery:
                return False
            if not proxy_domain_can_be_provisioned(record):
                return False
            if record.status in (ProxyRecord.Status.DELETING, ProxyRecord.Status.ERRORING):
                return False
            if record.status in (ProxyRecord.Status.WAITING, ProxyRecord.Status.TIMED_OUT):
                return True

        if not active:
            _deprovision_cloudflare_proxy(record)
            return False

        _restore_cloudflare_proxy(record)
        if record.needs_activation_recovery and record.status != ProxyRecord.Status.ISSUING:
            ProxyRecord.objects.filter(pk=record.pk).update(needs_activation_recovery=False)
        return True
