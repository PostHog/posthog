"""Shared alert identity and destination ownership models.

These models give every alert product (insight, logs, billing) a common identity
and a first-class destination concept, replacing the filter-based ownership
described in RFC "Explicit alert ownership and shared alert identity".

The shared root is named `AlertIdentity` rather than `Alert` because the legacy
`Alert` model (trends monitoring) still occupies that name; a later phase can
rename the root once the legacy model is removed.
"""

from __future__ import annotations

from django.db import models

from posthog.models.utils import UUIDModel


class AlertProduct(models.TextChoices):
    INSIGHT = "insight", "Insight"
    LOGS = "logs", "Logs"
    BILLING = "billing", "Billing"


class AlertIdentity(UUIDModel):
    """Shared identity for one user-visible alert across every alert product.

    Owns the durable tenant boundary (`organization`) and the team that runs
    evaluation and delivery (`execution_team`, nullable for organization-scoped
    products that can temporarily have no execution team). Product-specific
    configuration stays in one-to-one configuration models.
    """

    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="+",
    )
    # Nullable: organization-scoped alerts (billing) can outlive a deleted team.
    execution_team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.SET_NULL,
        related_name="+",
        db_column="execution_team_id",
        null=True,
        blank=True,
    )
    product = models.CharField(max_length=20, choices=AlertProduct.choices)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        db_table = "posthog_alertidentity"
        indexes = [
            models.Index(fields=["organization", "product"], name="alert_ident_org_product_idx"),
            models.Index(fields=["execution_team"], name="alert_ident_exec_team_idx"),
        ]

    def __str__(self) -> str:
        return f"AlertIdentity({self.product}:{self.id})"


class AlertDestination(UUIDModel):
    """One logical destination a user configures for an alert.

    Groups all executors (HogFunctions, and later HogFlows) that deliver
    notifications for that destination. Deleting the alert cascades to
    destinations, and deleting a destination cascades to its executors.
    """

    alert = models.ForeignKey(AlertIdentity, on_delete=models.CASCADE, related_name="destinations")
    type = models.CharField(max_length=20)
    name = models.CharField(max_length=400, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_alertdestination"
        indexes = [
            models.Index(fields=["alert"], name="alert_dest_alert_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} (Alert: {self.alert_id})"
