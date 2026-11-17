import uuid
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
    # Set while billing says a partner pays for the organization. A partner-paid organization still
    # gets its own Stripe customer, so this keeps the billing lock on after billing fills customer_id.
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


def record_partner_paid(organization_id: uuid.UUID, paid_by_partner: bool) -> None:
    """Billing sync calls this with billing's `paid_by_partner`. Billing sends every organization's status at
    least daily, so a mark that is wrong, or that outlived the partner's payer link, corrects itself."""
    rows = OrganizationProvisioning.objects.filter(organization_id=organization_id)
    if paid_by_partner:
        rows.paid_by_partner().filter(partner_paid_since__isnull=True).update(partner_paid_since=timezone.now())
    else:
        rows.filter(partner_paid_since__isnull=False).update(partner_paid_since=None)
