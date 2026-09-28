from django.db import models
from django.db.models import Q


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

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(partner="vercel", application__isnull=True)
                | (~Q(partner="vercel") & Q(application__isnull=False)),
                name="org_provisioning_application_matches_partner",
            )
        ]
