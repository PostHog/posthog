from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class AlertSeriesPoint(TeamScopedRootMixin):
    """One computed hourly bucket of a SQL detector alert's history.

    Buckets are reused between checks: the insert probe rescans hours that received late rows,
    and a daily full scan reconciles what no insert signal reveals (person merges). A bucket
    with no matching events keeps no row — the full scan omits it too, so a stored zero would
    invent a value. ``fingerprint`` discards the series when the query or settings change.
    """

    # db_constraint=False: a real FK would lock posthog_team (hot table) while migrating.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    # related_name="+" keeps these rows off every path that walks an alert's relations (the
    # activity log diffs each one); the unique constraint below already indexes alert_config.
    alert_config = models.ForeignKey(
        "alerts.AlertConfiguration", on_delete=models.CASCADE, related_name="+", db_index=False
    )

    bucket = models.DateTimeField()
    value = models.FloatField()
    fingerprint = models.CharField(max_length=64)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        # The unique index this constraint creates is also the read path's index: every query here
        # leads with alert_config and then narrows on bucket.
        constraints = [
            models.UniqueConstraint(fields=["alert_config", "bucket"], name="unique_alert_series_point_bucket"),
        ]

    def __str__(self) -> str:
        return f"{self.alert_config_id} @ {self.bucket.isoformat()} = {self.value}"


class AlertSeriesState(TeamScopedRootMixin):
    """Per-alert probe bookkeeping: ``watermark`` is the insert-time instant changed-bucket
    detection has covered, ``seeded_at`` the last full scan (which bounds the drift no insert
    signal reveals). One row per alert; a fingerprint mismatch counts as absent.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    alert_config = models.OneToOneField("alerts.AlertConfiguration", on_delete=models.CASCADE, related_name="+")

    fingerprint = models.CharField(max_length=64)
    watermark = models.DateTimeField()
    seeded_at = models.DateTimeField()
