from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
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


def event_match_sql_fragment(obj) -> str:
    """WHERE fragment that narrows to the matching event names.

    Returns an empty string when ``obj.delete_all_events`` is set, so callers can
    drop the ``event IN %(events)s`` filter without special-casing. Accepts both
    the Django model and the Dagster ``DeletionRequestContext`` dataclass.
    """
    if getattr(obj, "delete_all_events", False):
        return ""
    return "AND event IN %(events)s"


def event_match_params(obj) -> dict:
    """Params for the time-bounded event match (omits ``events`` when deleting all)."""
    params: dict = {
        "team_id": obj.team_id,
        "start_time": obj.start_time,
        "end_time": obj.end_time,
    }
    if not getattr(obj, "delete_all_events", False):
        params["events"] = obj.events
    return params


class RequestType(models.TextChoices):
    PROPERTY_REMOVAL = "property_removal"
    EVENT_REMOVAL = "event_removal"
    PERSON_REMOVAL = "person_removal"


class RequestStatus(models.TextChoices):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    QUEUED = "queued"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionMode(models.TextChoices):
    IMMEDIATE = "immediate"
    DEFERRED = "deferred"


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
        models.CharField(max_length=1024),
        blank=True,
        default=list,
        help_text="Event names to match. May be empty only when delete_all_events is true.",
    )
    delete_all_events = models.BooleanField(
        default=False,
        help_text="Opt in to deleting every event for the team in the given time range. "
        "Only honored for event_removal requests. Requires events to be empty.",
    )
    properties = ArrayField(
        models.CharField(max_length=1024),
        blank=True,
        default=list,
        help_text="Property names to remove. Required for property_removal requests.",
    )
    person_drop_profiles = models.BooleanField(null=True, blank=True, help_text="Drop person profiles.")
    person_drop_events = models.BooleanField(null=True, blank=True, help_text="Drop event records related to persons.")
    person_drop_recordings = models.BooleanField(null=True, blank=True, help_text="Drop person recordings.")

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
    created_by_staff = models.BooleanField(null=True, blank=True, help_text="Was this created by instance operator.")
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
    execution_mode = models.CharField(
        max_length=20,
        choices=ExecutionMode.choices,
        default=ExecutionMode.IMMEDIATE,
        help_text="Picked by ClickHouse Team at approval time. "
        "Immediate: run a dedicated delete mutation now. "
        "Deferred: queue event UUIDs into adhoc_events_deletion so the "
        "scheduled deletes_job drains them. Only honored for event_removal.",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"DataDeletionRequest({self.request_type}, team={self.team_id}, status={self.status})"

    def clean(self) -> None:
        super().clean()
        if self.request_type == RequestType.EVENT_REMOVAL:
            if self.delete_all_events and self.events:
                raise ValidationError(
                    {"events": "Events must be empty when delete_all_events is set."},
                )
            if not self.delete_all_events and not self.events:
                raise ValidationError(
                    {"events": "Provide at least one event, or set delete_all_events to delete every event."},
                )
        elif self.delete_all_events:
            raise ValidationError(
                {"delete_all_events": "delete_all_events is only valid for event_removal requests."},
            )
