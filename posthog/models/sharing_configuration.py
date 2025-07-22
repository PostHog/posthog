import secrets
from typing import cast, Optional
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.db import models, transaction
import structlog

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

    enabled = models.BooleanField(default=False)
    access_token = models.CharField(max_length=400, null=True, blank=True, unique=True)

    # Expiry for token rotation - null means active/current token
    expires_at = models.DateTimeField(
        null=True, blank=True, help_text="When this sharing configuration expires (null = active)"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            # Index for fast lookups by token and expiry
            models.Index(fields=["access_token", "expires_at"], name="sharing_token_expiry_idx"),
        ]

    def save(self, *args, **kwargs):
        # Generate initial token if this is a new object and no token is set
        if not self.pk and not self.access_token:
            self.access_token = self.generate_unique_token()
        super().save(*args, **kwargs)

    def generate_unique_token(self) -> str:
        """Generate a unique token with retry logic"""
        max_retries = 10

        for attempt in range(max_retries):
            new_token = get_default_access_token()

            # Check if token already exists (including expired ones)
            if not SharingConfiguration.objects.filter(access_token=new_token).exists():
                return new_token

            # Log collision only after first attempt
            if attempt > 0:
                logger.warn(
                    "sharing_token_collision_retry",
                    attempt=attempt,
                    team_id=self.team_id if hasattr(self, "team_id") else None,
                )

        raise Exception(f"Could not generate unique token after {max_retries} attempts")

    @classmethod
    def get_active_config_by_token(cls, token: str) -> Optional["SharingConfiguration"]:
        """Get non-expired sharing configuration by token"""
        try:
            return cls.objects.select_related("dashboard", "insight", "recording").get(
                access_token=token,
                enabled=True,
                expires_at__isnull=True,  # Only active (non-expired) configs
            )
        except cls.DoesNotExist:
            return None

    @classmethod
    def get_config_by_token_including_expired(cls, token: str) -> Optional["SharingConfiguration"]:
        """Get sharing configuration by token, including recently expired ones within grace period"""
        now = timezone.now()
        grace_period = timedelta(seconds=settings.SHARING_TOKEN_GRACE_PERIOD_SECONDS)

        try:
            return (
                cls.objects.select_related("dashboard", "insight", "recording")
                .filter(
                    access_token=token,
                    enabled=True,
                )
                .filter(
                    models.Q(expires_at__isnull=True)  # Active configs
                    | models.Q(expires_at__gt=now - grace_period)  # Recently expired within grace
                )
                .first()
            )
        except cls.DoesNotExist:
            return None

    def rotate_access_token(self) -> "SharingConfiguration":
        """Create a new sharing configuration and expire the current one"""
        if not self.enabled:
            raise ValueError("Cannot rotate token for disabled sharing configuration")

        with transaction.atomic():
            # Create new sharing configuration
            new_config = SharingConfiguration.objects.create(
                team=self.team,
                dashboard=self.dashboard,
                insight=self.insight,
                recording=self.recording,
                enabled=True,
                # access_token will be auto-generated in save()
            )

            # Expire current configuration
            self.expires_at = timezone.now() + timedelta(seconds=settings.SHARING_TOKEN_GRACE_PERIOD_SECONDS)
            self.save()

            logger.info(
                "sharing_token_rotated",
                old_config_id=self.pk,
                new_config_id=new_config.pk,
                team_id=self.team_id,
                new_token_preview=new_config.access_token[:8] + "..." if new_config.access_token else None,
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

            from posthog.models.dashboard import Dashboard

            return list(
                cast(Dashboard, self.dashboard)
                .tiles.filter(deleted=False)
                .exclude(insight__deleted=True)
                .values_list("insight_id", flat=True)
            )
        elif self.recording:
            return []
        else:
            return []

    def get_insight(self) -> "Insight":
        if self.insight:
            return self.insight

        if self.dashboard:
            return self.dashboard.tiles.filter(deleted=False).exclude(insight__deleted=True).first().insight

        raise ValueError("Attempted to get insight from a sharing configuration that is not tied to one")
