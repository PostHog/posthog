from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.alerts.backend.models.alert import AlertConfiguration, InvestigationStatus, InvestigationVerdict


class InsightAlertInvestigation(TeamScopedRootMixin, UUIDModel):
    """One investigation of one platform evaluation of an insight alert.

    The platform never writes `AlertCheck`, so an alert the platform evaluates keeps its
    investigations here. A row exists for every evaluation that asked for one, including one the
    claim refused, which is recorded as SKIPPED and spends no budget.
    """

    class Kind(models.TextChoices):
        AGENT = "agent", "Agent"
        METRICS = "metrics", "Metrics"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    alert_configuration = models.ForeignKey(AlertConfiguration, on_delete=models.CASCADE, related_name="+")
    # The platform's configuration. Not a foreign key, because that model belongs to another product.
    configuration_id = models.UUIDField()
    evaluation_key = models.CharField(max_length=255)
    # The firing the evaluation belongs to, which is what the per-episode budget counts. Null for
    # the firing that was already open when the platform took the alert over.
    episode_started_at = models.DateTimeField(null=True, blank=True)

    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=InvestigationStatus.choices)
    verdict = models.CharField(max_length=20, choices=InvestigationVerdict.choices, null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    notebook = models.ForeignKey(
        "notebooks.Notebook",
        on_delete=models.SET_NULL,
        db_constraint=False,
        db_index=False,
        null=True,
        blank=True,
        related_name="+",
    )
    error = models.JSONField(null=True, blank=True)
    # What the evaluation measured, as the agent reads it: value, triggered dates and points,
    # anomaly scores, interval and triggered metadata.
    evaluated = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "alerts_insightalertinvestigation"
        constraints = [
            models.UniqueConstraint(
                fields=["configuration_id", "evaluation_key"], name="insight_alert_investigation_one_per_evaluation"
            )
        ]
        indexes = [
            # The episode's budget and its last verdict.
            models.Index(
                fields=["configuration_id", "episode_started_at", "created_at"], name="insight_alert_inv_episode_idx"
            ),
            # Deleting a notebook nulls the link through this, and most rows have no notebook.
            models.Index(
                fields=["notebook"], name="insight_alert_inv_notebook_idx", condition=models.Q(notebook__isnull=False)
            ),
            # The claim's in-flight and cooldown checks.
            models.Index(fields=["configuration_id", "created_at"], name="insight_alert_inv_recent_idx"),
        ]
