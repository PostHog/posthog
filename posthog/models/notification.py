from django.db import models

from posthog.models.utils import UUIDModel


class NotificationPriority(models.TextChoices):
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class Notification(UUIDModel):
    """
    Unified notification model for all notification types.

    Developer Experience:
    - Generic resource_type allows any team to send notifications
    - Optional resource_id enables deep linking to specific items
    - Flexible context object for custom metadata
    - Priority levels for future sorting/filtering
    """

    # Who receives this notification
    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=True,
    )

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=True,
    )

    # What is this notification about?
    resource_type = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Type of resource (e.g., 'feature_flag', 'insight', 'alert', 'approval', 'workflow_error')",
    )

    resource_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Optional ID of the specific resource for deep linking",
    )

    # Notification content
    title = models.CharField(
        max_length=255,
        help_text="Brief notification title (e.g., 'Feature flag updated')",
    )

    message = models.TextField(
        help_text="Full notification message",
    )

    # Metadata
    context = models.JSONField(
        default=dict,
        help_text="Additional metadata for rendering (e.g., actor, changes, links)",
    )

    priority = models.CharField(
        max_length=16,
        choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL,
        db_index=True,
    )

    # State
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Timestamp when notification was marked as read",
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "posthog_notification"
        ordering = ["-created_at"]
        indexes = [
            # Efficient queries for user's unread notifications
            models.Index(fields=["user", "read_at", "-created_at"], name="notif_user_read_created_idx"),
            # Queries by resource type
            models.Index(fields=["team", "resource_type", "-created_at"], name="notif_team_type_created_idx"),
            # Count unread per user
            models.Index(fields=["user", "read_at"], name="notif_user_unread_idx"),
        ]

    def __str__(self):
        return f"{self.resource_type}: {self.title} (user={self.user_id})"

    def mark_as_read(self):
        """Mark this notification as read."""
        from django.utils import timezone

        if not self.read_at:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at"])
