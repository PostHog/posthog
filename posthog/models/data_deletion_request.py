from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel


def jsonhas_expr(prop: str, param_prefix: str) -> str:
    """Build a ClickHouse ``JSONHas`` expression for a (possibly nested) property path.

    Splits dotted names so ``"sub.prop"`` becomes
    ``JSONHas(properties, %(prefix_0)s, %(prefix_1)s)``.
    """
    parts = prop.split(".")
    args = ", ".join(f"%({param_prefix}_{i})s" for i in range(len(parts)))
    return f"JSONHas(properties, {args})"


class RequestType(models.TextChoices):
    PROPERTY_REMOVAL = "property_removal"
    EVENT_REMOVAL = "event_removal"


class RequestStatus(models.TextChoices):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class DataDeletionRequest(UUIDModel):
    # Request config
    team_id = models.IntegerField()
    request_type = models.CharField(
        max_length=40,
        choices=RequestType.choices,
        help_text="property_removal: remove specific properties from matching events. "
        "event_removal: delete entire events matching the criteria.",
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    events = ArrayField(
        models.CharField(max_length=400),
        help_text="Event names to match.",
    )
    properties = ArrayField(
        models.CharField(max_length=400),
        blank=True,
        default=list,
        help_text="Property names to remove. Required for property_removal requests.",
    )
    status = models.CharField(max_length=40, choices=RequestStatus.choices, default=RequestStatus.DRAFT)

    # Stats (populated by ClickHouse query)
    count = models.BigIntegerField(null=True, blank=True, help_text="Number of events matching criteria")
    part_count = models.IntegerField(null=True, blank=True, help_text="Number of ClickHouse parts")
    parts_size = models.BigIntegerField(null=True, blank=True)
    parts_row_count = models.BigIntegerField(null=True, blank=True)
    min_timestamp = models.DateTimeField(null=True, blank=True, help_text="Earliest timestamp of matching events.")
    max_timestamp = models.DateTimeField(null=True, blank=True, help_text="Latest timestamp of matching events.")
    stats_calculated_at = models.DateTimeField(null=True, blank=True)

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
    criteria_updated_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="data_deletion_requests_criteria_updated",
        help_text="Last user who changed deletion criteria (events, properties, time range, or request type).",
    )
    criteria_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When deletion criteria were last changed.",
    )

    # Approval workflow
    requires_approval = models.BooleanField(
        default=True,
        help_text="ClickHouse deletes are heavyweight mutations that can degrade query performance "
        "and increase disk usage while running. Approval ensures deletes are scheduled "
        "during low-traffic windows to avoid impacting production workloads.",
    )
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
