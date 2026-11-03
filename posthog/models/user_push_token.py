from typing import TYPE_CHECKING

from django.db import connection, models, transaction
from django.utils import timezone

from posthog.models.utils import UUIDModel

if TYPE_CHECKING:
    from posthog.models.user import User


class UserPushToken(UUIDModel):
    """Per-user push notification token for a mobile device.

    A user may register multiple tokens (one per device). Tokens are uploaded
    by the mobile app after the user grants notification permission, and used
    by backend services to fan out push notifications via the platform-native
    push service (Expo for the PostHog mobile app).
    """

    class Platform(models.TextChoices):
        IOS = "ios", "iOS"
        ANDROID = "android", "Android"
        WEB = "web", "Web"

    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="push_tokens",
    )
    token = models.TextField(
        help_text="Opaque push token issued by the platform push service (e.g. Expo push token).",
    )
    platform = models.CharField(
        max_length=16,
        choices=Platform.choices,
        help_text="Device platform the token was issued for.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(
        auto_now=True,
        help_text="Last time the mobile app re-registered this token. Bumped on every save.",
    )

    class Meta:
        db_table = "posthog_user_push_token"
        unique_together = [("user", "token")]

    @classmethod
    def register(cls, *, user: "User", token: str, platform: str) -> "UserPushToken":
        with transaction.atomic():
            # A row lock cannot serialize the first registration of a token. Lock its identity instead.
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"user-push-token:{token}"])
            cls.objects.filter(token=token).exclude(user=user).delete()
            # Include last_seen_at in defaults so update_or_create persists it on the update path too.
            push_token, _created = cls.objects.update_or_create(
                user=user,
                token=token,
                defaults={"platform": platform, "last_seen_at": timezone.now()},
            )
            return push_token
