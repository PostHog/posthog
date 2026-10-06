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
    # Billing decides who pays, so an organization is locked while billing reports a payer for it, even after the
    # partner's pays_for_customers flag is switched off: the flag doesn't stop billing from invoicing the partner.
    # Billing gives a partner-paid organization its own Stripe customer, so customer_id says nothing about who pays.
    # Before billing has linked a payer, an organization without a customer_id is locked when its partner has
    # pays_for_customers, so its members can't start self-serve billing first.
    provisioned = Q(provisioned_organizations__organization=organization)
    partner_pays = Q(provisioned_organizations__billing_has_payer=True)
    if not organization.customer_id:
        partner_pays |= Q(_provisioning_config__pays_for_customers=True)
    return OAuthApplication.objects.filter(provisioned & partner_pays).first()
