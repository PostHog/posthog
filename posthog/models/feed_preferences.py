from django.db import models

from posthog.models.utils import UUIDModel


class FeedActivityType(models.TextChoices):
    DASHBOARD = "dashboard", "New dashboards"
    EVENT_DEFINITION = "event_definition", "Event definitions"
    EXPERIMENT_LAUNCHED = "experiment_launched", "Experiments launched"
    EXPERIMENT_COMPLETED = "experiment_completed", "Experiments completed"
    EXTERNAL_DATA_SOURCE = "external_data_source", "Data connections"
    FEATURE_FLAG = "feature_flag", "Feature flags"
    SURVEY = "survey", "Surveys"
    REPLAY_PLAYLIST = "replay_playlist", "Replay playlists"
    EXPIRING_RECORDINGS = "expiring_recordings", "Expiring recordings"


class FeedPreferences(UUIDModel):
    """User preferences for home feed per team"""

    user = models.ForeignKey("User", on_delete=models.CASCADE)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    # Activity type preferences (default all True)
    enabled_types = models.JSONField(default=dict)

    # Feed enabled/disabled per team
    feed_enabled = models.BooleanField(default=True)

    # AI summarization preferences
    ai_summarization_enabled = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user"],
                name="unique_feed_preferences_per_user_team",
            )
        ]
        indexes = [
            models.Index(fields=["user", "team"]),
        ]

    @property
    def enabled_activity_types(self) -> list[str]:
        """Returns list of enabled activity types"""
        return [activity_type for activity_type, enabled in self.enabled_types.items() if enabled]

    @staticmethod
    def get_default_enabled_types() -> dict[str, bool]:
        """Get default enabled types (all True)"""
        return {choice[0]: True for choice in FeedActivityType.choices}
