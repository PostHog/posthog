from uuid import UUID

from redis.lock import Lock

from posthog.models import ProxyRecord
from posthog.models.proxy_record import is_reserved_proxy_domain, org_may_register_reserved_domain
from posthog.redis import get_client
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
    return not is_reserved_proxy_domain(record.domain) or org_may_register_reserved_domain(
        record.organization_id, record.domain
    )


def _restore_cloudflare_proxy(record: ProxyRecord) -> None:
    hostname = get_custom_hostname_by_domain(record.domain)
    if hostname is None:
        try:
            create_custom_hostname(record.domain)
        except CloudflareAPIError as error:
            if not any(item.get("code") == 1406 for item in error.errors):
                raise
    if record.root_redirect_url:
        update_cloudflare_proxy_root_redirect(record.domain, record.root_redirect_url)


def reconcile_cloudflare_proxy(organization_id: str | UUID, proxy_record_id: str | UUID) -> bool:
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
            if not proxy_domain_can_be_provisioned(record):
                return False
            if record.status in (ProxyRecord.Status.DELETING, ProxyRecord.Status.ERRORING):
                return False
            if record.status in (ProxyRecord.Status.WAITING, ProxyRecord.Status.TIMED_OUT):
                return True

        if not active:
            hostname = get_custom_hostname_by_domain(record.domain)
            if hostname:
                delete_custom_hostname(hostname.id)
            update_cloudflare_proxy_root_redirect(record.domain, None)
            return False

        _restore_cloudflare_proxy(record)
        return True
