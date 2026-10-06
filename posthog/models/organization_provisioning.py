from typing import TYPE_CHECKING

from posthog.models.oauth import OAuthApplication

if TYPE_CHECKING:
    from posthog.models.organization import Organization


def get_billing_lock_partner(organization: "Organization") -> OAuthApplication | None:
    if organization.partner_payer_detached_at is not None:
        return None
    if organization.provisioning_application_id is None:
        return None
    applications = OAuthApplication.objects.all()
    if not organization.billing_has_payer:
        if organization.customer_id:
            return None
        applications = applications.filter(_provisioning_config__pays_for_customers=True)
    return applications.filter(pk=organization.provisioning_application_id).first()
