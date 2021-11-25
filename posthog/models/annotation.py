from django.db import models
from django.utils import timezone


class Annotation(models.Model):
    class Scope(models.TextChoices):
        DASHBOARD_ITEM = "dashboard_item", "dashboard item"
        PROJECT = "project", "project"
        ORGANIZATION = "organization", "organization"

    class CreationType(models.TextChoices):
        USER = "USR", "user"
        GITHUB = "GIT", "GitHub"

    content: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now, null=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    dashboard_item: models.ForeignKey = models.ForeignKey(
        "posthog.Insight", on_delete=models.SET_NULL, null=True, blank=True
    )
    team: models.ForeignKey = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    organization: models.ForeignKey = models.ForeignKey("posthog.Organization", on_delete=models.CASCADE, null=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    scope = models.CharField(max_length=24, choices=Scope.choices, default=Scope.DASHBOARD_ITEM)
    creation_type = models.CharField(max_length=3, choices=CreationType.choices, default=CreationType.USER,)
    date_marker: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)

    # DEPRECATED: replaced by scope
    apply_all: models.BooleanField = models.BooleanField(null=True)

    def get_analytics_metadata(self):
        return {"scope": str(self.scope), "date_marker": self.date_marker}
