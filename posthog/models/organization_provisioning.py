import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from django.db import models
from django.db.models import F, Q, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from posthog.models.oauth import OAuthApplication

if TYPE_CHECKING:
    from posthog.models.organization import Organization


class OrganizationProvisioningQuerySet(models.QuerySet["OrganizationProvisioning"]):
    def paid_by_partner(self) -> "OrganizationProvisioningQuerySet":
        # A join would turn the UPDATE into `pk IN (SELECT ...)`, which Postgres doesn't re-check after a row-lock wait.
        paying = OAuthApplication.objects.filter(_provisioning_config__pays_for_customers=True).values("id")
        return self.filter(application_id__in=paying)


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
    # computed_at of the billing status that last set partner_paid_since, so an older status can't undo it.
    partner_paid_status_at = models.DateTimeField(null=True, blank=True)

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


def record_partner_paid(organization_id: uuid.UUID, paid_by_partner: bool, computed_at: datetime | None) -> None:
    """Billing sync calls this with billing's `paid_by_partner`. Billing's daily sync sends every organization it
    hasn't saved for a day, so a mark that is wrong, or that outlived the partner's payer link, corrects itself.

    One conditional UPDATE writes the mark and the status time together, and skips a status older than the one
    that last wrote it. So a delayed status, or a sync that fails after this, can't leave the two out of step."""
    rows = OrganizationProvisioning.objects.filter(organization_id=organization_id)
    changes: dict[str, object] = {}
    if computed_at is not None:
        rows = rows.filter(Q(partner_paid_status_at__isnull=True) | Q(partner_paid_status_at__lt=computed_at))
        changes["partner_paid_status_at"] = computed_at
    if paid_by_partner:
        rows.paid_by_partner().update(
            partner_paid_since=Coalesce(F("partner_paid_since"), Value(timezone.now())), **changes
        )
    else:
        rows.update(partner_paid_since=None, **changes)
