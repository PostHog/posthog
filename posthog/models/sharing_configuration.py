import secrets
from typing import cast
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.db import models, transaction, IntegrityError

from posthog.models.insight import Insight


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

    previous_access_token = models.CharField(
        max_length=400,
        null=True,
        blank=True,
        db_index=True,
        help_text="Previous access token, valid during grace period",
    )
    token_rotated_at = models.DateTimeField(null=True, blank=True, help_text="When the current token was rotated")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Generate initial token if this is a new object and no token is set
        if not self.pk and not self.access_token:
            self.generate_initial_token()
        super().save(*args, **kwargs)

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
            # Check whether this

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

    def is_token_valid(self, token: str) -> bool:
        """Check if a token is valid (current or within grace period)"""
        if token == self.access_token:
            return True

        # Check if it's the previous token within grace period
        if (
            token == self.previous_access_token
            and self.previous_access_token
            and self.token_rotated_at
            and timezone.now() - self.token_rotated_at < timedelta(seconds=settings.SHARING_TOKEN_GRACE_PERIOD_SECONDS)
        ):
            return True

        return False

    def rotate_access_token(self) -> str:
        """Rotate the access token with retry logic to handle race conditions"""
        max_retries = 10

        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    # Store previous token
                    self.previous_access_token = self.access_token

                    # Generate new token
                    new_token = get_default_access_token()

                    # Check if token already exists anywhere in the table
                    if SharingConfiguration.objects.filter(
                        models.Q(access_token=new_token) | models.Q(previous_access_token=new_token)
                    ).exists():
                        # Token collision - try again with new token
                        continue

                    # Update fields
                    self.access_token = new_token
                    self.token_rotated_at = timezone.now()

                    # Save with the new token
                    self.save()

                    return new_token

            except IntegrityError:
                # Database constraint violation (token collision) - retry
                if attempt == max_retries - 1:
                    raise
                continue

        raise Exception(f"Could not generate unique token after {max_retries} attempts")

    def generate_initial_token(self) -> str:
        """Generate initial token with retry logic for new sharing configurations"""
        max_retries = 10

        for attempt in range(max_retries):
            try:
                new_token = get_default_access_token()

                # Check if token already exists anywhere in the table
                if SharingConfiguration.objects.filter(
                    models.Q(access_token=new_token) | models.Q(previous_access_token=new_token)
                ).exists():
                    continue

                self.access_token = new_token
                return new_token

            except IntegrityError:
                if attempt == max_retries - 1:
                    raise
                continue

        raise Exception(f"Could not generate unique initial token after {max_retries} attempts")
