from django.contrib.postgres.fields import ArrayField
from django.db import models

from products.event_definitions.backend.models import EventDefinition


class EnterpriseEventDefinition(EventDefinition):
    owner = models.ForeignKey(
        "posthog.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="event_definitions",
    )
    description = models.TextField(blank=True, null=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL, blank=True)
    verified = models.BooleanField(default=False, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        "posthog.User",
        null=True,
        on_delete=models.SET_NULL,
        blank=True,
        related_name="verifying_user",
    )
    hidden = models.BooleanField(null=True, blank=True, default=False)
    # Set when the event's ingestion is stopped. A periodic task deletes the definition after this time.
    scheduled_deletion_at = models.DateTimeField(null=True, blank=True)
    # When the event's ingestion was stopped. The periodic task gives up 7 days after this.
    ingestion_stopped_at = models.DateTimeField(null=True, blank=True)
    # Store default columns for event definition view, similar to team.live_events_columns
    default_columns = ArrayField(models.TextField(), null=True, blank=True)

    # Deprecated in favour of app-wide tagging model. See EnterpriseTaggedItem
    deprecated_tags: ArrayField = ArrayField(models.CharField(max_length=32), null=True, blank=True, default=list)
    deprecated_tags_v2: ArrayField = ArrayField(
        models.CharField(max_length=32),
        null=True,
        blank=True,
        default=None,
        db_column="tags",
    )

    class Meta:
        indexes = [
            models.Index(
                fields=["scheduled_deletion_at"],
                name="ee_eventdef_sched_del_idx",
                condition=models.Q(scheduled_deletion_at__isnull=False),
            ),
        ]
