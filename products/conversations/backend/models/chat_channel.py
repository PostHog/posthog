from django.db import models

from posthog.models.utils import UUIDModel


class ChatChannel(UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="chat_channels")
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True, default="")
    is_default = models.BooleanField(default=False)
    created_by = models.ForeignKey("posthog.User", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_chat_channel"
        indexes = [
            models.Index(fields=["team", "name"], name="posthog_con_chat_chan_team_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="unique_chat_channel_name_per_team"),
        ]

    def __str__(self) -> str:
        return f"#{self.name} (team={self.team_id})"


class ChatChannelMembership(models.Model):
    channel = models.ForeignKey(ChatChannel, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="chat_channel_memberships")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_conversations_chat_channel_membership"
        constraints = [
            models.UniqueConstraint(fields=["channel", "user"], name="unique_chat_channel_membership"),
        ]

    def __str__(self) -> str:
        return f"User {self.user_id} in #{self.channel.name}"
