from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel


class RequestType(models.TextChoices):
    PROPERTY_REMOVAL = "property_removal"
    EVENT_REMOVAL = "event_removal"


class RequestStatus(models.TextChoices):
    PENDING = "pending"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class DataDeletionRequest(UUIDModel):
    # Request config
    team_id = models.IntegerField()
    request_type = models.CharField(max_length=40, choices=RequestType.choices)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    events = ArrayField(models.CharField(max_length=400))
    properties = ArrayField(models.CharField(max_length=400), blank=True, default=list)
    status = models.CharField(max_length=40, choices=RequestStatus.choices, default=RequestStatus.PENDING)

    # Stats
    count = models.BigIntegerField(null=True, blank=True)
    part_count = models.IntegerField(null=True, blank=True)
    parts_size = models.BigIntegerField(null=True, blank=True)

    # Metadata
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="data_deletion_requests_created",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    # Approval workflow
    requires_approval = models.BooleanField(default=True)
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="data_deletion_requests_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"DataDeletionRequest({self.request_type}, team={self.team_id}, status={self.status})"
