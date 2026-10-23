from datetime import datetime
from typing import Any

from django.db import models
from django.utils import timezone


class DeletionRunJob(models.TextChoices):
    SQUASH_PERSON_OVERRIDES = "squash_person_overrides"
    DELETES = "deletes_job"


class DeletionRunStatus(models.TextChoices):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class DeletionRunLog(models.Model):
    """One row per squash_person_overrides or deletes_job Dagster run, for staff to read in Django admin.

    deletes_job only loads person deletions requested at or before its watermark, the oldest
    _timestamp left in person_distinct_id_overrides. The other deletions are left for a later run
    and nothing else records that, so this log keeps the watermark and the skipped count per run.
    """

    dagster_run_id = models.CharField(max_length=64, unique=True)
    parent_run_id = models.CharField(
        max_length=64, null=True, blank=True, help_text="Set when this run is a re-execution of that run."
    )
    job = models.CharField(max_length=40, choices=DeletionRunJob.choices)
    status = models.CharField(max_length=20, choices=DeletionRunStatus.choices, default=DeletionRunStatus.RUNNING)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    # squash_person_overrides: the overrides with _timestamp before this cutoff are folded into the events.
    squash_cutoff = models.DateTimeField(null=True, blank=True)
    squash_limit = models.BigIntegerField(null=True, blank=True)

    # deletes_job: person deletions with created_at after the watermark are not loaded in this run.
    watermark = models.DateTimeField(null=True, blank=True)
    limited_to_team_id = models.IntegerField(
        null=True, blank=True, help_text="Set when the run was limited to one team."
    )
    loaded_counts = models.JSONField(default=dict, blank=True, help_text="Loaded deletions per deletion type.")
    skipped_person_deletions = models.IntegerField(null=True, blank=True)
    oldest_skipped_created_at = models.DateTimeField(null=True, blank=True)
    watermark_holders = models.JSONField(
        default=list, blank=True, help_text="Teams with the oldest overrides, which keep the watermark back."
    )

    # A re-execution reuses the outputs of the steps it skips, so it inherits what those steps recorded.
    INHERITED_FIELDS = (
        "squash_cutoff",
        "squash_limit",
        "watermark",
        "limited_to_team_id",
        "loaded_counts",
        "skipped_person_deletions",
        "oldest_skipped_created_at",
        "watermark_holders",
    )

    class Meta:
        indexes = [models.Index(fields=["job", "status", "-started_at"], name="deletion_run_log_latest")]

    @classmethod
    def record(
        cls,
        dagster_run_id: str,
        job: DeletionRunJob,
        parent_run_id: str | None,
        started_at: datetime | None = None,
        **fields: Any,
    ) -> None:
        """Create the run's row on its first write and update it on every later one.

        started_at is only used when this write creates the row, because the first write can come from any step.
        """
        inherited = (
            cls.objects.filter(dagster_run_id=parent_run_id).values(*cls.INHERITED_FIELDS).first()
            if parent_run_id
            else None
        )
        cls.objects.update_or_create(
            dagster_run_id=dagster_run_id,
            defaults={"job": job, **fields},
            create_defaults={
                **(inherited or {}),
                "job": job,
                "parent_run_id": parent_run_id,
                "started_at": started_at or timezone.now(),
                **fields,
            },
        )
