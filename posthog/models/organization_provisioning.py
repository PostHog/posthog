from typing import TYPE_CHECKING

from django.db import models
from django.db.models import Q

from posthog.models.oauth import OAuthApplication

if TYPE_CHECKING:
    from posthog.models.organization import Organization


class OrganizationProvisioning(models.Model):
    class Partner(models.TextChoices):
        PROVISIONING_API = "provisioning_api"
        STRIPE_PROJECTS = "stripe_projects"
        VERCEL = "vercel"

    # db_constraint=False: posthog_organization is hot, and the FK constraint would lock it.
    organization = models.OneToOneField(
        "posthog.Organization",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="partner_provisioning",
        db_constraint=False,
    )
    partner = models.CharField(max_length=32, choices=Partner.choices)
    # Vercel calls PostHog with Vercel-signed tokens, not through a PostHog OAuth application,
    # so a Vercel row has no application to reference.
    application = models.ForeignKey(
        "posthog.OAuthApplication",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="provisioned_organizations",
    )
    billing_has_payer = models.BooleanField(default=False, db_default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(partner="vercel", application__isnull=True)
                | Q(partner__in=["provisioning_api", "stripe_projects"], application__isnull=False),
                name="org_provisioning_application_matches_partner",
            )
        ]


def get_billing_lock_partner(organization: "Organization") -> OAuthApplication | None:
    # customer_id is the organization's own Stripe customer, synced from billing. Billing gives one to
    # a partner-paid organization too, so for an organization with a Stripe customer the lock follows
    # billing_has_payer. Without a payer, that organization pays for itself and keeps self-serve billing.
    provisioned = Q(provisioned_organizations__organization=organization)
    if organization.customer_id:
        provisioned &= Q(provisioned_organizations__billing_has_payer=True)
    return OAuthApplication.objects.filter(provisioned, _provisioning_config__pays_for_customers=True).first()
