from django.db import models

from posthog.models.utils import UUIDTModel


class PushPlatform(models.TextChoices):
    ANDROID = "android"
    IOS = "ios"
    WEB = "web"


class PushSubscription(UUIDTModel):
    """
    Stores push notification tokens for devices.

    Tokens are stored here (not as person properties) for security - person properties
    are readable via API, but FCM tokens should not be exposed.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    distinct_id = models.CharField(max_length=512)
    token = models.TextField()
    platform = models.CharField(max_length=16, choices=PushPlatform.choices)

    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "distinct_id"]),
            models.Index(fields=["team", "token"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "distinct_id", "token"],
                name="unique_team_distinct_id_token",
            )
        ]

    def __str__(self) -> str:
        return f"PushSubscription({self.distinct_id}, {self.platform}, active={self.is_active})"

    @classmethod
    def upsert_token(
        cls,
        team_id: int,
        distinct_id: str,
        token: str,
        platform: PushPlatform,
    ) -> "PushSubscription":
        """
        Create or update a push subscription token.

        If a subscription with the same team/distinct_id/token exists, updates it.
        Also deactivates any other tokens for this distinct_id on the same platform
        (a user typically only has one active device per platform).
        """
        subscription, created = cls.objects.update_or_create(
            team_id=team_id,
            distinct_id=distinct_id,
            token=token,
            defaults={
                "platform": platform,
                "is_active": True,
            },
        )

        if not created:
            subscription.is_active = True
            subscription.platform = platform
            subscription.save(update_fields=["is_active", "platform", "updated_at"])

        return subscription

    @classmethod
    def get_active_tokens_for_distinct_id(
        cls,
        team_id: int,
        distinct_id: str,
        platform: PushPlatform | None = None,
    ) -> list["PushSubscription"]:
        """Get all active push subscriptions for a distinct_id."""
        qs = cls.objects.filter(team_id=team_id, distinct_id=distinct_id, is_active=True)
        if platform:
            qs = qs.filter(platform=platform)
        return list(qs)

    @classmethod
    def deactivate_token(cls, team_id: int, token: str) -> int:
        """
        Deactivate a specific token (e.g., when FCM reports it as invalid).
        Returns the number of subscriptions deactivated.
        """
        return cls.objects.filter(team_id=team_id, token=token, is_active=True).update(is_active=False)
