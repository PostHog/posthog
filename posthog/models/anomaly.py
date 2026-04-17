from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.db import models

from posthog.models.utils import UUIDTModel


class InsightAnomalyConfig(UUIDTModel):
    """Per-insight anomaly scoring configuration and scheduling state.

    Created lazily by the discovery task for eligible insights.
    Absence means the insight hasn't been picked up for scoring yet.
    """

    created_at = models.DateTimeField(auto_now_add=True)

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    insight = models.OneToOneField("posthog.Insight", on_delete=models.CASCADE, related_name="anomaly_config")

    excluded = models.BooleanField(default=False)

    last_scored_at = models.DateTimeField(null=True, blank=True)
    next_score_due_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # Training state
    last_trained_at = models.DateTimeField(null=True, blank=True)
    model_storage_key = models.CharField(max_length=500, blank=True, default="")
    model_version = models.IntegerField(default=0)

    interval = models.CharField(max_length=20, blank=True, default="")
    detector_config = models.JSONField(default=dict)

    class Meta:
        indexes = [
            models.Index(fields=["team_id", "excluded"], name="anomaly_cfg_team_excluded"),
        ]

    def __str__(self) -> str:
        return f"AnomalyConfig for insight {self.insight_id} (team {self.team_id})"


class AnomalyScore(UUIDTModel):
    """Individual anomaly scoring result for a single data point in a series."""

    created_at = models.DateTimeField(auto_now_add=True)

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE, related_name="anomaly_scores")

    series_index = models.IntegerField()
    series_label = models.CharField(max_length=400, blank=True, default="")

    timestamp = models.DateTimeField()
    score = models.FloatField()
    is_anomalous = models.BooleanField()

    interval = models.CharField(max_length=20, blank=True, default="")
    data_snapshot = models.JSONField(default=dict)

    scored_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["team_id", "is_anomalous", "-scored_at"], name="anomaly_score_team_anom_scored"),
            models.Index(
                fields=["team_id", "insight_id", "series_index", "-timestamp"],
                name="anomaly_score_team_insight_ts",
            ),
        ]

    def __str__(self) -> str:
        return f"AnomalyScore {self.score:.2f} for insight {self.insight_id} series {self.series_index} at {self.timestamp}"

    @classmethod
    def clean_up_old_scores(cls) -> int:
        # Retention matches the longest window the tab offers (1y). Keeping
        # scores older than the widest dropdown option just means we're
        # storing rows nothing can ever surface, so this ceiling is the
        # practical cap — bump both together if a longer window is added.
        retention_days = 365
        oldest_allowed = datetime.now(UTC) - timedelta(days=retention_days)
        count, _ = cls.objects.filter(scored_at__lt=oldest_allowed).delete()
        return count
