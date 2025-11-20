from django.db import models

from posthog.models.utils import UUIDModel


class NotificationPreference(UUIDModel):
    """
    User notification preferences per team.

    Controls which notification types a user wants to receive.
    Defaults to opt-in model (all notifications enabled).

    Performance:
    - Cached in Redis with key: notif_prefs:{user_id}:{team_id}
    - Cache invalidated on save/delete via Django signals
    - Batch queried for preference filtering during fan-out
    """

    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="notification_preferences",
        db_index=True,
    )

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="notification_preferences",
        db_index=True,
    )

    resource_type = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Type of resource (e.g., 'feature_flag', 'insight', 'alert')",
    )

    enabled = models.BooleanField(
        default=True,
        help_text="Whether user wants to receive this notification type",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_notification_preference"
        unique_together = [["user", "team", "resource_type"]]
        indexes = [
            # Efficient preference lookups during fan-out
            models.Index(fields=["team", "resource_type"]),
            # User preference management UI
            models.Index(fields=["user", "team"]),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.resource_type} ({'enabled' if self.enabled else 'disabled'})"
