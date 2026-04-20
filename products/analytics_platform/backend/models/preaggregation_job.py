from django.db import models

from posthog.models.utils import CreatedMetaFields, UUIDModel


class PreaggregationJob(CreatedMetaFields, UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        STALE = "stale", "Stale"
        FAILED = "failed", "Failed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, editable=False)

    # Time range this job covers
    time_range_start = models.DateTimeField()
    time_range_end = models.DateTimeField()

    # Normalized query representation for matching
    query_hash = models.CharField(max_length=64)  # SHA256 hash for quick lookup

    # Status tracking
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    computed_at = models.DateTimeField(null=True, blank=True)

    # TTL: when the preaggregated data expires in ClickHouse
    # Jobs with expires_at in the past should not be used
    expires_at = models.DateTimeField(null=True, blank=True)

    # Timestamps (created_at from CreatedMetaFields, created_by also included)
    updated_at = models.DateTimeField(auto_now=True)

    # Error tracking
    error = models.TextField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team_id", "query_hash"]),
            models.Index(fields=["team_id", "status"]),
            models.Index(fields=["team_id", "time_range_start", "time_range_end"]),
            models.Index(fields=["team_id", "expires_at"]),
        ]

        constraints = [
            models.CheckConstraint(
                check=models.Q(time_range_start__lt=models.F("time_range_end")),
                name="time_range_start_before_end",
            ),
        ]
