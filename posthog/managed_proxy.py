from uuid import UUID

from redis.lock import Lock

from posthog.cloud_utils import is_cloud
from posthog.models import ProxyRecord
from posthog.models.proxy_record import (
    CLOUDFLARE_DEPROVISIONED_STATES,
    CLOUDFLARE_RECOVERY_STATES,
    CloudflareActivationState,
    is_reserved_proxy_domain,
    org_may_register_reserved_domain,
)
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


def restore_cloudflare_proxy(record: ProxyRecord) -> None:
    if record.cloudflare_activation_state in CLOUDFLARE_DEPROVISIONED_STATES:
        next_state = (
            CloudflareActivationState.RECOVERY_PENDING
            if record.cloudflare_activation_state == CloudflareActivationState.SUSPENDED
            else CloudflareActivationState.IDLE
        )
        # A later suspension must clean up even if only part of restoration succeeds.
        ProxyRecord.objects.filter(pk=record.pk).update(cloudflare_activation_state=next_state)
    hostname = get_custom_hostname_by_domain(record.domain)
    if hostname is None:
        try:
            create_custom_hostname(record.domain)
        except CloudflareAPIError as error:
            if not any(item.get("code") == 1406 for item in error.errors):
                raise
    if record.root_redirect_url:
        update_cloudflare_proxy_root_redirect(record.domain, record.root_redirect_url)
    if (
        record.status in (ProxyRecord.Status.VALID, ProxyRecord.Status.WARNING)
        and record.cloudflare_activation_state in CLOUDFLARE_RECOVERY_STATES
    ):
        ProxyRecord.objects.filter(pk=record.pk).update(cloudflare_activation_state=CloudflareActivationState.IDLE)


def deprovision_cloudflare_proxy(record: ProxyRecord) -> None:
    """Clean up a suspended proxy while the caller holds its reconciliation lock."""
    if record.cloudflare_activation_state in CLOUDFLARE_DEPROVISIONED_STATES:
        return
    hostname = get_custom_hostname_by_domain(record.domain)
    recovery_pending = record.cloudflare_activation_state == CloudflareActivationState.RECOVERY_PENDING
    needs_recovery = (
        recovery_pending
        or record.status in (ProxyRecord.Status.ISSUING, ProxyRecord.Status.VALID, ProxyRecord.Status.WARNING)
        or (record.status == ProxyRecord.Status.ERRORING and hostname is not None)
    )
    # Record the intent first so a partial Cloudflare cleanup can still be recovered.
    if needs_recovery and not recovery_pending:
        ProxyRecord.objects.filter(pk=record.pk).update(
            cloudflare_activation_state=CloudflareActivationState.RECOVERY_PENDING
        )
    if hostname:
        delete_custom_hostname(hostname.id)
    update_cloudflare_proxy_root_redirect(record.domain, None)
    final_state = CloudflareActivationState.SUSPENDED if needs_recovery else CloudflareActivationState.DEPROVISIONED
    ProxyRecord.objects.filter(pk=record.pk).update(cloudflare_activation_state=final_state)


def provision_cloudflare_hostname(
    organization_id: UUID, proxy_record_id: UUID, *, recovering_certificate: bool = False
) -> bool:
    with cloudflare_proxy_lock(proxy_record_id):
        record = (
            ProxyRecord.objects.filter(
                organization_id=organization_id,
                pk=proxy_record_id,
            )
            .exclude(organization__is_active=False)
            .exclude(organization__is_pending_deletion=True)
            .exclude(status=ProxyRecord.Status.DELETING)
            .first()
        )
        if record is None or not is_cloudflare_proxy(record) or not proxy_domain_can_be_provisioned(record):
            return False
        if recovering_certificate and (
            record.status not in (ProxyRecord.Status.ISSUING, ProxyRecord.Status.ERRORING)
            or record.cloudflare_activation_state not in CLOUDFLARE_RECOVERY_STATES
        ):
            return False
        if not recovering_certificate and record.status == ProxyRecord.Status.ERRORING:
            return False
        if record.status not in (ProxyRecord.Status.WAITING, ProxyRecord.Status.TIMED_OUT):
            restore_cloudflare_proxy(record)
        return True
