from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UUIDModel


class SyncTrigger(models.TextChoices):
    # A run started automatically as a child of the underlying warehouse sync.
    SCHEDULED = "scheduled", "scheduled"
    # The same warehouse sync, started from the UI ("Sync now"). Rides the scheduled pipeline, so the
    # activity records its outcome as "scheduled" — the recorder keeps this trigger on the row so the
    # history still shows who asked for it.
    SYNC = "sync", "sync"
    # A full-table backfill the user kicked off from the UI (the "Backfill" button).
    MANUAL = "manual", "manual"
    # A full-table read from S3 to populate historical rows a new/changed mapping never saw.
    BACKFILL = "backfill", "backfill"


class SyncStatus(models.TextChoices):
    RUNNING = "running", "running"
    COMPLETED = "completed", "completed"
    FAILED = "failed", "failed"


class CustomPropertySyncRun(TeamScopedRootMixin, UUIDModel, CreatedMetaFields):
    """One person-property sync run for a single source. Persists the funnel counts the sync/backfill
    activities compute (which otherwise live only in Prometheus/logs) so the UI can show run history
    and how many person profiles were affected."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )

    source = models.ForeignKey(
        "customer_analytics.CustomPropertySource", on_delete=models.CASCADE, related_name="sync_runs"
    )
    # The warehouse object the rows came from — exactly one is set, matching the source's binding.
    # Both are plain ids (not FKs) because a schema or view can be deleted while its historical runs
    # stay meaningful.
    schema_id = models.UUIDField(null=True, blank=True)
    saved_query_id = models.UUIDField(null=True, blank=True)
    # The warehouse job this run rode on: an import job, or a view materialization. Null for
    # backfill/manual runs, which read the table directly instead of riding a job.
    job_id = models.CharField(max_length=400, null=True, blank=True)

    trigger = models.CharField(max_length=20, choices=SyncTrigger.choices)
    status = models.CharField(max_length=20, choices=SyncStatus.choices, default=SyncStatus.RUNNING)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # Funnel: read -> changed (survived the snapshot diff) -> existing (distinct_id resolved to a
    # person) -> produced (intent on Kafka); skipped_missing_person is the changed rows that dropped
    # because no person matched.
    rows_read = models.PositiveIntegerField(default=0)
    changed = models.PositiveIntegerField(default=0)
    existing = models.PositiveIntegerField(default=0)
    produced = models.PositiveIntegerField(default=0)
    skipped_missing_person = models.PositiveIntegerField(default=0)

    error = models.TextField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["team", "source", "-created_at"], name="cpsr_team_source_created_idx")]
