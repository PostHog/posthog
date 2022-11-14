from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.utils import UUIDModel


class DashboardTemplate(UUIDModel):
    class Scope(models.TextChoices):
        PROJECT = "project", "project"
        ORGANIZATION = "organization", "organization"
        GLOBAL = "global", "global"

    scope = models.CharField(max_length=24, choices=Scope.choices, default=Scope.PROJECT)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE, null=True)
    organization: models.ForeignKey = models.ForeignKey("posthog.Organization", on_delete=models.CASCADE, null=True)

    template_name: models.CharField = models.CharField(max_length=400, null=True)
    source_dashboard: models.IntegerField = models.IntegerField(null=True)
    dashboard_description: models.CharField = models.CharField(max_length=400, null=True)
    dashboard_filters: models.JSONField = models.JSONField(null=True)
    tiles: models.JSONField = models.JSONField(default=list)
    tags: ArrayField = ArrayField(models.CharField(max_length=255), default=list)
    deleted: models.BooleanField = models.BooleanField(default=False)

    def __repr__(self) -> str:
        return f"<DashboardTemplate: {self.template_name}, scope={self.scope}, team={self.team_id}, org={self.organization_id}, deleted={self.deleted}>"
