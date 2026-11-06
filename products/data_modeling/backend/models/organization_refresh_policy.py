from django.db import models


class OrganizationRefreshPolicy(models.Model):
    """Billing's last known package status; an absent row means it has not been synced."""

    organization = models.OneToOneField(
        "posthog.Organization", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+"
    )
    has_paid_package = models.BooleanField()
    billing_status_computed_at = models.DateTimeField(null=True, blank=True)
