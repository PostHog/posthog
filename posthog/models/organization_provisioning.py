import uuid
from collections.abc import Collection
from typing import TYPE_CHECKING

from django.db import models
from django.db.models import Q
from django.utils import timezone

from posthog.models.oauth import OAuthApplication

if TYPE_CHECKING:
    from posthog.models.organization import Organization


class OrganizationProvisioningQuerySet(models.QuerySet["OrganizationProvisioning"]):
    def paid_by_partner(self) -> "OrganizationProvisioningQuerySet":
        return self.filter(application___provisioning_config__pays_for_customers=True)


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
    created_at = models.DateTimeField(auto_now_add=True)
    # Set when the organization's first Stripe customer arrives while its partner pays for it. That
    # customer is the partner's, so the billing lock stays on after billing fills customer_id.
    partner_paid_since = models.DateTimeField(null=True, blank=True)

    objects = OrganizationProvisioningQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(partner="vercel", application__isnull=True)
                | Q(partner__in=["provisioning_api", "stripe_projects"], application__isnull=False),
                name="org_provisioning_application_matches_partner",
            )
        ]


def get_billing_lock_partner(organization: "Organization") -> OAuthApplication | None:
    provisioning = OrganizationProvisioning.objects.paid_by_partner().filter(organization=organization)
    # customer_id is the organization's Stripe customer, synced from billing. An organization that has
    # one pays for itself and keeps self-serve billing to manage it, unless partner_paid_since says
    # the customer is the one billing created for the partner's subscription.
    if organization.customer_id:
        provisioning = provisioning.filter(partner_paid_since__isnull=False)
    row = provisioning.select_related("application").first()
    return row.application if row is not None else None


def mark_partner_paid(organization_ids: Collection[uuid.UUID]) -> int:
    """Billing sync calls this for an organization's first customer_id. Until then a paying partner locks the
    organization's billing, so it can't add a payment method, and that first Stripe customer is the one
    billing created for the partner's subscription. Returns how many organizations it marked."""
    return (
        OrganizationProvisioning.objects.paid_by_partner()
        .filter(organization_id__in=organization_ids, partner_paid_since__isnull=True)
        .update(partner_paid_since=timezone.now())
    )
