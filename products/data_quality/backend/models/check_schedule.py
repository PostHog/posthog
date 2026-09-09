from datetime import timedelta

from django.db import models
from django.utils import timezone

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from ..facade.enums import subject_type_choices


class DataQualityCheckSchedule(
    ModelActivityMixin, TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel
):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    subject_type = models.CharField(max_length=32, choices=subject_type_choices)
    subject_uuid = models.UUIDField()
    interval = models.DurationField(default=timedelta(days=1))
    enabled = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(default=timezone.now)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_suite_run = models.ForeignKey(
        "data_quality.DataQualitySuiteRun", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "subject_type", "subject_uuid"], name="unique_quality_schedule_subject"
            )
        ]
        indexes = [models.Index(fields=["enabled", "next_run_at"], name="quality_schedule_due_idx")]
