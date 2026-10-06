from typing import TYPE_CHECKING

from posthog.models.oauth import OAuthApplication

if TYPE_CHECKING:
    from posthog.models.organization import Organization


def get_billing_lock_partner(organization: "Organization") -> OAuthApplication | None:
    if organization.customer_id or organization.provisioning_application_id is None:
        return None
    return OAuthApplication.objects.filter(
        pk=organization.provisioning_application_id, _provisioning_config__pays_for_customers=True
    ).first()
