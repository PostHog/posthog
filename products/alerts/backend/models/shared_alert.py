from __future__ import annotations

from django.db import models

from posthog.models.utils import CreatedMetaFields, UUIDModel


class AlertProduct(models.TextChoices):
    INSIGHT = "insight", "Insight"
    LOGS = "logs", "Logs"
    BILLING = "billing", "Billing"


class AlertSharedIdentity(UUIDModel, CreatedMetaFields):
    """Shared identity for every alert, across products.

    One row per user-visible alert. Product evaluation configuration stays in
    one-to-one models (`AlertConfiguration`, `LogsAlertConfiguration`,
    `BillingAlertConfiguration`); this row only establishes identity, tenant
    scope, and the destination ownership root.

    `organization` is the durable tenant boundary; `execution_team` says where
    evaluation and delivery run. Insight and logs alerts always have an
    execution team. Billing alerts are organization-owned and can have none —
    e.g. while re-homing after team deletion.

    Named `AlertSharedIdentity` because `alerts.Alert` is the deprecated
    insight-alert model still occupying that name in this app (`posthog_alert`).
    """

    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="shared_alerts",
        # Organization deletion clears every team too, so cascade ordering is not
        # a concern; the constraint-free FK keeps org teardown lock-free.
        db_constraint=False,
    )
    execution_team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="shared_alerts",
        db_constraint=False,
    )
    product = models.CharField(max_length=16, choices=AlertProduct.choices)

    class Meta:
        db_table = "alerts_sharedalert"

    def __str__(self) -> str:
        return f"{self.product} alert {self.id}"


class AlertDestination(UUIDModel, CreatedMetaFields):
    """One logical destination a user configured for an alert.

    A destination owns one executor (HogFunction) per alert event kind —
    e.g. a Slack destination for a logs alert owns four HogFunctions, one per
    event kind. The executors carry the secrets and executable inputs; this row
    carries what is needed to identify, list, authorize, and delete the group.
    """

    class Type(models.TextChoices):
        SLACK = "slack", "Slack"
        DISCORD = "discord", "Discord"
        WEBHOOK = "webhook", "Webhook"
        TEAMS = "teams", "Microsoft Teams"

    # Real FK constraint: `alerts_sharedalert` is not a hot table, so the database
    # can enforce the alert → destination relationship the RFC asks for.
    shared_alert = models.ForeignKey(
        "alerts.AlertSharedIdentity",
        on_delete=models.CASCADE,
        related_name="destinations",
    )
    type = models.CharField(max_length=16, choices=Type.choices)
    name = models.CharField(max_length=400, blank=True)

    class Meta:
        db_table = "alerts_alertdestination"

    def __str__(self) -> str:
        return f"{self.type} destination {self.id} (alert {self.shared_alert_id})"
