from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.utils import CreatedMetaFields, RootTeamMixin, UUIDModel


class PulseDigestStatus(models.TextChoices):
    PENDING = "pending"
    GENERATING = "generating"
    DELIVERED = "delivered"
    FAILED = "failed"


class PulseFindingFeedback(models.TextChoices):
    PENDING = "pending"
    THUMBS_UP = "up"
    THUMBS_DOWN = "down"
    DISMISSED = "dismissed"
    SNOOZED = "snoozed"


class PulseSubscriptionFrequency(models.TextChoices):
    WEEKLY = "weekly"
    DAILY = "daily"


class DetectionMode(models.TextChoices):
    CHANGE_V1 = "change_v1"
    DISCOVERY = "discovery"  # v2 seam — rejected at API validation in v1


class Sensitivity(models.TextChoices):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    SENSITIVE = "sensitive"
    CUSTOM = "custom"


# Single source of truth for sensitivity → (min_change_pct, robust_z_threshold).
# CUSTOM intentionally absent: it reads the subscription's own fields.
SENSITIVITY_PRESETS: dict[str, tuple[float, float]] = {
    Sensitivity.CONSERVATIVE: (0.40, 3.5),
    Sensitivity.BALANCED: (0.25, 3.5),
    Sensitivity.SENSITIVE: (0.15, 3.0),
}


class PulseDigest(RootTeamMixin, CreatedMetaFields, UUIDModel):
    """One run of the Pulse scan workflow for a team. Holds 0..N findings."""

    team = models.ForeignKey("Team", on_delete=models.CASCADE, related_name="pulse_digests")
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=PulseDigestStatus.choices,
        default=PulseDigestStatus.PENDING,
    )
    workflow_run_id = models.CharField(max_length=255, blank=True, default="")
    error = models.JSONField(null=True, blank=True)

    objects = TeamScopedManager()  # type: ignore[misc]

    class Meta:
        indexes = [
            models.Index(fields=["team", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"PulseDigest(team={self.team_id}, {self.period_start.date()} → {self.period_end.date()})"


class PulseFinding(RootTeamMixin, CreatedMetaFields, UUIDModel):
    """A single metric change Pulse found worth surfacing in a digest."""

    team = models.ForeignKey("Team", on_delete=models.CASCADE, related_name="pulse_findings")
    digest = models.ForeignKey(PulseDigest, on_delete=models.CASCADE, related_name="findings")

    # The metric the finding is about — opaque JSON descriptor describing event(s), filters, breakdown
    metric_descriptor = models.JSONField()
    metric_label = models.CharField(max_length=255, blank=True, default="")

    current_value = models.FloatField()
    baseline_value = models.FloatField()  # holds the baseline median
    change_pct = models.FloatField()
    impact = models.FloatField()  # abs(change_pct) * sqrt(baseline_median) — used for ranking
    robust_z = models.FloatField()  # secondary/informational only

    # The breakdown the LLM picked as most explanatory (if any) — e.g. {"$browser": "Safari"}
    attribution_breakdown = models.JSONField(null=True, blank=True)

    narrative = models.TextField()
    chart_thumbnail_url = models.URLField(max_length=2048, blank=True, default="")

    feedback = models.CharField(
        max_length=20,
        choices=PulseFindingFeedback.choices,
        default=PulseFindingFeedback.PENDING,
    )
    feedback_user = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="pulse_feedback"
    )
    feedback_at = models.DateTimeField(null=True, blank=True)
    snoozed_until = models.DateTimeField(null=True, blank=True)

    rank = models.IntegerField(default=0)

    objects = TeamScopedManager()  # type: ignore[misc]

    class Meta:
        indexes = [
            models.Index(fields=["digest", "rank"]),
            models.Index(fields=["digest", "feedback"]),
        ]
        ordering = ["rank", "-created_at"]

    def __str__(self) -> str:
        return f"PulseFinding({self.metric_label}, {self.change_pct:+.0%})"


class PulseSubscription(RootTeamMixin, ModelActivityMixin, CreatedMetaFields, UUIDModel):
    """Per-team config for how/when Pulse runs and how sensitive detection is."""

    team = models.OneToOneField("Team", on_delete=models.CASCADE, related_name="pulse_subscription")

    enabled = models.BooleanField(default=False)
    frequency = models.CharField(
        max_length=10,
        choices=PulseSubscriptionFrequency.choices,
        default=PulseSubscriptionFrequency.WEEKLY,
    )
    detection_mode = models.CharField(
        max_length=20,
        choices=DetectionMode.choices,
        default=DetectionMode.CHANGE_V1,
    )
    sensitivity = models.CharField(
        max_length=20,
        choices=Sensitivity.choices,
        default=Sensitivity.BALANCED,
    )
    # CUSTOM sensitivity reads these directly; presets override them at resolution time.
    min_change_pct = models.FloatField(default=0.25)
    baseline_weeks = models.IntegerField(default=4)
    max_findings = models.IntegerField(default=5)
    robust_z_threshold = models.FloatField(default=3.5)  # secondary signal only

    last_scan_at = models.DateTimeField(null=True, blank=True)
    next_scan_at = models.DateTimeField(null=True, blank=True)

    objects = TeamScopedManager()  # type: ignore[misc]

    def resolve_sensitivity(self) -> tuple[float, float]:
        """Return effective (min_change_pct, robust_z_threshold).

        Non-custom sensitivities derive from SENSITIVITY_PRESETS (single
        source of truth); CUSTOM reads the model's own fields.
        """
        if self.sensitivity in SENSITIVITY_PRESETS:
            return SENSITIVITY_PRESETS[self.sensitivity]
        return (self.min_change_pct, self.robust_z_threshold)

    def __str__(self) -> str:
        return f"PulseSubscription(team={self.team_id}, {self.frequency}, enabled={self.enabled})"
