from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

import structlog

from posthog.models.utils import UUIDTModel

logger = structlog.get_logger(__name__)


class HogFlowBatchJob(UUIDTModel):
    """
    Stores the status and other meta information for a batch of HogFlow jobs (typically used for a broadcast)
    """

    class Meta:
        indexes = [
            models.Index(fields=["status", "team"]),
        ]

    class State(models.TextChoices):
        QUEUED = "queued"
        ACTIVE = "active"
        COMPLETED = "completed"
        CANCELLED = "cancelled"
        FAILED = "failed"

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=State.choices, default=State.QUEUED)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    filters = models.JSONField(default=dict)

    def __str__(self):
        return f"HogFlow batch run {self.id}"


@receiver(post_save, sender=HogFlowBatchJob)
def handle_hog_flow_batch_job_created(sender, instance, created, **kwargs):
    if created:
        # Handle new batch job creation
        pass
