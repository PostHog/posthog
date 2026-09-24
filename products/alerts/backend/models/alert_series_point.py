from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class AlertSeriesPoint(TeamScopedRootMixin):
    """One already-computed hourly bucket of a SQL detector alert's history.

    A detector alert needs its whole window of bucketed values on every check, but every bucket
    except the most recent ones is a closed hour that cannot change. Caching those values lets a
    check scan only the recent tail instead of the full window.

    A row exists only for a bucket the query returned. A bucket with no matching events is
    represented by the absence of a row, never by a zero — the full scan omits it too, and
    writing a zero would feed the detector a value it would never otherwise see.

    ``fingerprint`` ties the row to the query text and alert settings that produced it, so
    editing either makes every cached row unusable instead of silently mixing series.
    """

    # db_constraint=False: a real FK constraint would take a SHARE ROW EXCLUSIVE lock on
    # posthog_team (a hot table) while migrating.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    # related_name="+": nothing reads these rows through the alert, and a reverse accessor would
    # put them in front of every framework path that walks an alert's relations — the activity log
    # diffs each one in full, and this manager refuses a query with no team context.
    # db_index=False: the unique constraint below already indexes alert_config as its leading
    # column, and a second index on the same column only costs writes.
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
    """Per-alert bookkeeping for the cached series: how fresh it is and where the probe left off.

    ``watermark`` is the insert-time instant up to which changed buckets have been detected and
    applied; the next check probes ``events_recent`` for rows inserted after it. ``seeded_at``
    records the last full scan, so identity drift the probe cannot see (person merges, dedup
    collapses) is bounded by a scheduled reseed rather than accumulating forever.

    One row per alert. A fingerprint mismatch on read means the series it describes is gone, so
    the state counts as absent and the next check reseeds.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    alert_config = models.OneToOneField("alerts.AlertConfiguration", on_delete=models.CASCADE, related_name="+")

    fingerprint = models.CharField(max_length=64)
    watermark = models.DateTimeField()
    seeded_at = models.DateTimeField()
