from typing import Optional

from django.db import models
from django.utils import timezone


class Annotation(models.Model):
    class Scope(models.TextChoices):
        INSIGHT = "dashboard_item", "insight"
        DASHBOARD = "dashboard", "dashboard"
        PROJECT = "project", "project"
        ORGANIZATION = "organization", "organization"
        RECORDING = "recording", "recording"

    class CreationType(models.TextChoices):
        USER = "USR", "user"
        GITHUB = "GIT", "GitHub"

    content = models.CharField(max_length=400, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    dashboard_item = models.ForeignKey("posthog.Insight", on_delete=models.SET_NULL, null=True, blank=True)
    dashboard = models.ForeignKey("posthog.Dashboard", on_delete=models.SET_NULL, null=True, blank=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    organization = models.ForeignKey("posthog.Organization", on_delete=models.CASCADE, null=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    scope = models.CharField(max_length=24, choices=Scope.choices, default=Scope.INSIGHT)
    creation_type = models.CharField(max_length=3, choices=CreationType.choices, default=CreationType.USER)
    date_marker = models.DateTimeField(null=True, blank=True)
    deleted = models.BooleanField(default=False)
    # we don't want a foreign key, since not all recordings will be in postgres
    recording_id = models.UUIDField(null=True, blank=True)

    # convenience so that we can load just emoji annotations, without checking the content
    is_emoji = models.BooleanField(default=False, null=True, blank=True)

    # DEPRECATED: replaced by scope
    apply_all = models.BooleanField(null=True)

    @property
    def insight_short_id(self) -> Optional[str]:
        return self.dashboard_item.short_id if self.dashboard_item is not None else None

    @property
    def insight_name(self) -> Optional[str]:
        return self.dashboard_item.name if self.dashboard_item is not None else None

    @property
    def insight_derived_name(self) -> Optional[str]:
        return self.dashboard_item.derived_name if self.dashboard_item is not None else None

    @property
    def dashboard_name(self) -> Optional[str]:
        return self.dashboard.name if self.dashboard is not None else None

    def get_analytics_metadata(self):
        return {"scope": str(self.scope), "date_marker": self.date_marker}
