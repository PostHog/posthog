from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class IncidentScope(models.TextChoices):
    VOLUME = "volume", "Overall volume"
    CHANNEL = "channel", "Channel"
    PRIORITY = "priority", "Priority"
    RULE = "rule", "Alert rule"


class IncidentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    RESOLVED = "resolved", "Resolved"
    DISMISSED = "dismissed", "Dismissed"


class TicketIncident(TeamScopedRootMixin, UUIDModel):
    """A detected ticket-volume anomaly (potential incident).

    The open ACTIVE row doubles as the dedup/cooldown: while one exists for a
    (team, scope, dimension_value) the detector never fires a duplicate, and
    auto-resolve happens by updating the row rather than via external state.
    """

    # db_constraint=False: a real FK constraint would take SHARE ROW EXCLUSIVE on the
    # hot posthog_team table on CreateModel. App-level enforcement is enough here.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)

    scope = models.CharField(max_length=20, choices=IncidentScope)
    # Discriminator within the scope: the channel/priority value, or the rule id for
    # rule-scoped incidents. Empty for overall volume. Non-null so the partial unique
    # constraint below covers every scope (Postgres treats NULLs as distinct).
    dimension_value = models.CharField(max_length=64, default="", blank=True)
    rule = models.ForeignKey(
        "conversations.TicketAlertRule",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidents",
    )

    status = models.CharField(max_length=20, choices=IncidentStatus, default=IncidentStatus.ACTIVE)
    detected_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    window_minutes = models.PositiveIntegerField()
    observed_count = models.PositiveIntegerField()
    # Null for absolute-only rule breaches, which have no baseline comparison.
    baseline_value = models.FloatField(null=True, blank=True)
    zscore = models.FloatField(null=True, blank=True)
    # Context snapshot for the UI and alert payload: sample ticket numbers, hourly
    # sparkline, channel mix — whatever the detector saw at fire time.
    details = models.JSONField(default=dict, blank=True)

    # Consecutive detector runs below the resolve threshold; auto-resolve triggers
    # once this reaches the detector's calm-run limit.
    calm_run_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_ticket_incident"
        indexes = [
            models.Index(fields=["team", "status"], name="posthog_con_incident_stat_idx"),
            models.Index(fields=["team", "-detected_at"], name="posthog_con_incident_det_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "scope", "dimension_value"],
                condition=models.Q(status="active"),
                name="posthog_con_incident_active_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"TicketIncident {self.scope}:{self.dimension_value or 'overall'} ({self.status}, team {self.team_id})"
