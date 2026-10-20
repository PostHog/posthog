from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.team import Team
from posthog.rbac.decorators import field_access_control


class TeamHeatmapConfig(models.Model):
    class CaptureMode(models.TextChoices):
        ALL = "all", "All URLs"
        URL_ALLOWLIST = "url_allowlist", "Only listed URLs"

    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False)

    screenshot_secret = field_access_control(
        models.CharField(max_length=200, null=True, blank=True), "project", "admin"
    )
    allowed_hostnames = field_access_control(
        ArrayField(models.CharField(max_length=253), default=list, blank=True, db_default=[]), "project", "admin"
    )

    capture_mode = field_access_control(
        models.CharField(
            max_length=20,
            choices=CaptureMode.choices,
            default=CaptureMode.URL_ALLOWLIST,
            db_default=CaptureMode.URL_ALLOWLIST,
        ),
        "project",
        "admin",
    )
    capture_url_allowlist = field_access_control(
        ArrayField(models.CharField(max_length=2000), default=list, blank=True, db_default=[]), "project", "admin"
    )
    capture_enforcement_started_at = models.DateTimeField(null=True, blank=True)
