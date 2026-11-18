import requests
import structlog
from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)


class TransientBillingSyncError(Exception):
    """Billing did not take the member sync, but a later attempt can succeed."""


@shared_task(
    ignore_result=True,
    rate_limit="5/s",
    autoretry_for=(TransientBillingSyncError,),
    retry_backoff=30,
    retry_backoff_max=600,
    max_retries=5,
)
@skip_team_scope_audit
def sync_members_to_billing(organization_id: str) -> None:
    from posthog.cloud_utils import get_cached_instance_license, is_cloud
    from posthog.models import Organization

    from ee.billing.billing_manager import (
        BillingManager,
        BillingServiceRateLimited,
        BillingServiceResponseError,
        get_billing_authorizer,
    )

    license = get_cached_instance_license()
    if not is_cloud() or license is None:
        return

    # Every attempt reads the organization again, so a retry sends the members as they are now.
    organization = Organization.objects.get(id=organization_id)
    authorizer = get_billing_authorizer(organization)
    if not authorizer:
        logger.warning("billing_member_sync_skipped_without_admin", organization_id=organization_id)
        return

    try:
        BillingManager(license, authorizer).sync_organization_users(organization)
    except (requests.ConnectionError, requests.Timeout, BillingServiceRateLimited) as e:
        raise TransientBillingSyncError(f"Billing member sync failed: {type(e).__name__}") from e
    except BillingServiceResponseError as e:
        # Billing answers any other 4xx the same way on every attempt, so only a timeout or a server error retries.
        if e.status_code == 408 or e.status_code >= 500:
            raise TransientBillingSyncError(f"Billing member sync failed: status {e.status_code}") from e
        raise


@shared_task(ignore_result=True, rate_limit="5/s")
@skip_team_scope_audit
def sync_from_billing(organization_id: str) -> None:
    from posthog.cloud_utils import get_cached_instance_license
    from posthog.models import Organization

    from ee.billing.billing_manager import BillingManager

    license = get_cached_instance_license()
    billing_manager = BillingManager(license, None)

    organization = Organization.objects.get(id=organization_id)
    billing_manager.get_billing(organization, {})
