from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class InsightAnomalyConfig(TeamScopedRootMixin, UUIDModel):
    """Per-insight overrides for anomaly scoring. Sparse: a row exists only when a user
    changes something, and every null field falls back to the global default."""

    # Targets a hot table, so the FK carries no database constraint: creating one
    # locks posthog_team against every write while it is taken. Django still
    # cascades, because it collects related rows itself when deleting a team.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    insight = models.OneToOneField("product_analytics.Insight", on_delete=models.CASCADE, related_name="anomaly_config")

    enabled = models.BooleanField(null=True, blank=True)
    # Same shape as AlertConfiguration.detector_config (the DetectorConfig union), so any
    # registered alerts detector can score an insight.
    detector_config = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class InsightAnomalyState(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    insight = models.OneToOneField("product_analytics.Insight", on_delete=models.CASCADE, related_name="anomaly_state")

    # Hash of the insight query and effective config. A change clears skip_reason and the failure
    # count, so an edited insight gets a fresh try.
    query_hash = models.CharField(max_length=64, blank=True, default="")
    last_scored_bucket = models.DateTimeField(null=True, blank=True)
    next_due_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0, db_default=0)
    # Set for failures that a retry cannot fix, such as an unsupported query shape.
    # The dispatcher skips the insight until its query changes.
    skip_reason = models.CharField(max_length=200, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["next_due_at"], name="insight_anomaly_next_due_idx")]
