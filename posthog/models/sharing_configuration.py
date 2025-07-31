import secrets
from typing import cast, Any
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.db import models
import structlog
from pydantic import BaseModel, Field

from posthog.models.insight import Insight

logger = structlog.get_logger(__name__)


class SharingConfigurationSettings(BaseModel):
    """Pydantic model for sharing configuration settings with clear defaults."""

    whitelabel: bool = Field(default=False, description="Hide PostHog branding")
    noHeader: bool = Field(default=False, description="Hide the header section")
    showInspector: bool = Field(default=False, description="Show the data inspector panel")
    legend: bool = Field(default=False, description="Show chart legend")
    detailed: bool = Field(default=False, description="Show detailed view")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SharingConfigurationSettings":
        """Create SharingConfigurationSettings from a dictionary, filtering only known fields."""
        known_fields = cls.model_fields.keys()
        filtered_data = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered_data)

    def merge_with_query_params(self, query_params: dict[str, Any]) -> "SharingConfigurationSettings":
        """Merge current settings with query parameters, with query params taking precedence."""
        merged_data = self.model_dump()

        # Only update fields that exist in query_params and are known fields
        for field_name in self.model_fields.keys():
            if field_name in query_params:
                # Convert query param presence to boolean (query params are strings)
                merged_data[field_name] = bool(query_params[field_name])

        return SharingConfigurationSettings(**merged_data)


def get_default_access_token() -> str:
    return secrets.token_urlsafe(22)


class SharingConfiguration(models.Model):
    # Relations
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    dashboard = models.ForeignKey("posthog.Dashboard", on_delete=models.CASCADE, null=True)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE, null=True)
    recording = models.ForeignKey(
        "SessionRecording",
        related_name="sharing_configurations",
        on_delete=models.CASCADE,
        to_field="session_id",
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True, blank=True)

    enabled = models.BooleanField(default=False)
    access_token = models.CharField(
        max_length=400,
        null=True,
        blank=True,
        default=get_default_access_token,
        unique=True,
    )

    expires_at = models.DateTimeField(
        null=True, blank=True, help_text="When this sharing configuration expires (null = active)"
    )

    settings = models.JSONField(null=True, blank=True, help_text="JSON settings for storing configuration options")

    def rotate_access_token(self) -> "SharingConfiguration":
        """Create a new sharing configuration and expire the current one"""

        new_config = SharingConfiguration.objects.create(
            team=self.team,
            dashboard=self.dashboard,
            insight=self.insight,
            recording=self.recording,
            enabled=self.enabled,
            settings=self.settings,
        )

        # Expire current configuration
        self.expires_at = timezone.now() + timedelta(seconds=settings.SHARING_TOKEN_GRACE_PERIOD_SECONDS)
        self.save()

        logger.info(
            "sharing_token_rotated",
            old_config_id=self.pk,
            new_config_id=new_config.pk,
            team_id=self.team_id,
        )

        return new_config

    def can_access_object(self, obj: models.Model):
        if obj.team_id != self.team_id:  # type: ignore
            return False

        if obj._meta.object_name == "Insight" and self.dashboard:
            return cast(Insight, obj).id in self.get_connected_insight_ids()

        for comparison in [self.insight, self.dashboard, self.recording]:
            if comparison and comparison == obj:
                return True

        return False

    def get_connected_insight_ids(self) -> list[int]:
        if self.insight:
            if self.insight.deleted:
                return []
            return [self.insight.id]
        elif self.dashboard:
            if self.dashboard.deleted:
                return []
            # Check whether this sharing configuration's dashboard contains this insight
            return list(self.dashboard.tiles.exclude(insight__deleted=True).values_list("insight__id", flat=True))
        return []
