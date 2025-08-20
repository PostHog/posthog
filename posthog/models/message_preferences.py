from django.db import models
from typing import Optional
from posthog.models.utils import UUIDTModel
import uuid

ALL_MESSAGE_PREFERENCE_CATEGORY_ID = "$all"


class PreferenceStatus(models.TextChoices):
    OPTED_IN = "OPTED_IN"
    OPTED_OUT = "OPTED_OUT"
    NO_PREFERENCE = "NO_PREFERENCE"


class MessageRecipientPreference(UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(default=False)
    identifier = models.CharField(max_length=512)
    preferences = models.JSONField(default=dict)

    class Meta:
        unique_together = (
            "team",
            "identifier",
        )

    def __str__(self) -> str:
        return f"Preferences for {self.identifier}"

    def set_preference(self, category_id: uuid.UUID, status: PreferenceStatus) -> None:
        """Set preference for a specific category"""
        if not isinstance(status, PreferenceStatus):
            raise ValueError(f"Status must be a PreferenceStatus enum, got {type(status)}")

        self.preferences[str(category_id)] = status.value
        self.save(update_fields=["preferences", "updated_at"])

    def get_preference(self, category_id: uuid.UUID) -> PreferenceStatus:
        """Get preference for a specific category"""
        status = self.preferences.get(str(category_id), PreferenceStatus.NO_PREFERENCE.value)
        return PreferenceStatus(status)

    def get_all_preferences(self) -> dict[uuid.UUID, PreferenceStatus]:
        """Get all preferences as a dictionary of UUID to PreferenceStatus"""
        return {uuid.UUID(category_id): PreferenceStatus(status) for category_id, status in self.preferences.items()}

    @classmethod
    def get_or_create_for_identifier(
        cls, team_id: int, identifier: str, defaults: Optional[dict[uuid.UUID, PreferenceStatus]] = None
    ) -> "MessageRecipientPreference":
        """Get or create preferences for an identifier"""
        if defaults is None:
            defaults = {}

        preferences_dict = {str(category_id): status.value for category_id, status in defaults.items()}

        instance, _ = cls.objects.get_or_create(
            team_id=team_id, identifier=identifier, defaults={"preferences": preferences_dict}
        )
        return instance
