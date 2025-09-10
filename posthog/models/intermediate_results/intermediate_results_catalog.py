# posthog/models/intermediate_results.py
import datetime
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

GENERATION_TIMEOUT_MINUTES = 30


class IntermediateResultsCatalog(models.Model):
    """
    Catalog table tracking which intermediate results are available for which date ranges.
    Used for distributed locking and coordination when computing query intermediate results.
    """

    class Status(models.TextChoices):
        COMPUTING = "computing", "Computing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    results_key = models.TextField(
        help_text="Hash of normalized query, hogql modifiers, path cleaning rules, etc (excluding date range)"
    )
    start_bucket = models.DateTimeField()
    end_bucket = models.DateTimeField()
    computed_at = models.DateTimeField()

    # Distributed locking and concurrency control
    insert_id = models.BigIntegerField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.COMPUTING, help_text="Current status of this computation"
    )
    locked_by = models.TextField(help_text="Identifier of the process/worker that acquired the lock")
    locked_at = models.DateTimeField(default=timezone.now, help_text="When the lock was acquired")
    clickhouse_query_id = models.TextField(
        null=True, blank=True, help_text="ClickHouse query ID for tracking the computation query"
    )

    class Meta:
        db_table = "intermediate_results_catalog"
        # Django doesn't support composite primary keys, so we use unique_together
        # and let Django create its own auto-incrementing primary key
        unique_together = [["results_key", "start_bucket", "end_bucket"]]
        indexes = [
            models.Index(fields=["results_key", "start_bucket", "end_bucket"]),
            models.Index(fields=["status", "locked_at"]),
            models.Index(fields=["results_key", "status"]),
        ]

    def __str__(self):
        return f"IntermediateResults({self.results_key}, {self.insert_id}, {self.start_bucket} - {self.end_bucket}, {self.status})"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        if not self.start_bucket or not self.end_bucket:
            raise ValidationError("start_bucket and end_bucket must be set")
        if self.start_bucket >= self.end_bucket:
            raise ValidationError("start_bucket must be less than end_bucket")

    def is_locked(self, now: datetime.datetime):
        if self.status != self.Status.COMPUTING:
            return False

        lock_timeout = now - timedelta(minutes=GENERATION_TIMEOUT_MINUTES)
        return self.locked_at > lock_timeout

    @property
    def duration_hours(self):
        """Get the duration of this bucket in hours"""
        return (self.end_bucket - self.start_bucket).total_seconds() / 3600
