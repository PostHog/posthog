from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import CreatedMetaFields, UUIDTModel

PULSE_ACTIVITY_SCOPE = "Pulse"
PULSE_ACTIVITY_VERB = "surfaced"
PULSE_DIGEST_READY_EVENT = "$pulse_digest_ready"


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


class PulseDigest(CreatedMetaFields, UUIDTModel):
    """One run of the Pulse scan workflow for a team. Holds 0..N findings."""

    team = models.ForeignKey("Team", on_delete=models.CASCADE, related_name="pulse_digests")
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=PulseDigestStatus.choices,
        default=PulseDigestStatus.PENDING,
    )
    delivered_to = models.JSONField(default=dict, blank=True)
    workflow_run_id = models.CharField(max_length=255, blank=True, default="")
    error = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"PulseDigest(team={self.team_id}, {self.period_start.date()} → {self.period_end.date()})"


class PulseFinding(CreatedMetaFields, UUIDTModel):
    """A single metric change Pulse found worth surfacing in a digest."""

    digest = models.ForeignKey(PulseDigest, on_delete=models.CASCADE, related_name="findings")

    # The metric the finding is about — opaque JSON descriptor describing event(s), filters, breakdown
    metric_descriptor = models.JSONField()
    metric_label = models.CharField(max_length=255, blank=True, default="")

    current_value = models.FloatField()
    baseline_value = models.FloatField()
    change_pct = models.FloatField()
    z_score = models.FloatField()

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

    class Meta:
        indexes = [
            models.Index(fields=["digest", "rank"]),
            models.Index(fields=["digest", "feedback"]),
        ]
        ordering = ["rank", "-created_at"]

    def __str__(self) -> str:
        return f"PulseFinding({self.metric_label}, {self.change_pct:+.0%})"


class PulseSubscription(ModelActivityMixin, CreatedMetaFields, UUIDTModel):
    """Per-team config for how/when Pulse delivers digests."""

    team = models.OneToOneField("Team", on_delete=models.CASCADE, related_name="pulse_subscription")

    enabled = models.BooleanField(default=False)
    frequency = models.CharField(
        max_length=10,
        choices=PulseSubscriptionFrequency.choices,
        default=PulseSubscriptionFrequency.WEEKLY,
    )
    # Which channels are enabled — subset of {"in_app", "slack", "email"}
    enabled_channels = models.JSONField(default=list, blank=True)
    slack_channel_id = models.CharField(max_length=64, blank=True, default="")
    email_recipients = models.JSONField(default=list, blank=True)

    last_scan_at = models.DateTimeField(null=True, blank=True)
    next_scan_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"PulseSubscription(team={self.team_id}, {self.frequency}, enabled={self.enabled})"
