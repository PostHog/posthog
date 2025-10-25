import secrets
from datetime import timedelta
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from posthog.models.share_password import SharePassword

from django.conf import settings
from django.db import models
from django.utils import timezone

import structlog

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models.insight import Insight

logger = structlog.get_logger(__name__)


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

    password_required = models.BooleanField(default=False)

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

    def generate_password_protected_token(self, share_password: "SharePassword") -> str:
        """
        Generate a JWT token for password-protected sharing access.
        This token is time-limited and scoped to the specific SharePassword used for authentication.
        """
        if not self.password_required:
            raise ValueError("Cannot generate password-protected token for non-password-protected sharing")

        return encode_jwt(
            payload={
                "share_password_id": share_password.id,
                "team_id": self.team_id,
                "access_token": self.access_token,  # Include for validation
            },
            expiry_delta=timedelta(hours=24),  # 24-hour session duration
            audience=PosthogJwtAudience.SHARING_PASSWORD_PROTECTED,
        )

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
