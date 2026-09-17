from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.team import Team
from posthog.rbac.decorators import field_access_control


class TeamHeatmapConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False)

    screenshot_secret = field_access_control(
        models.CharField(max_length=200, null=True, blank=True), "project", "admin"
    )
    allowed_hostnames = field_access_control(
        ArrayField(models.CharField(max_length=253), default=list, blank=True, db_default=[]), "project", "admin"
    )
