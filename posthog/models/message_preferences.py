from django.db import models
from django.core.signing import TimestampSigner, SignatureExpired, BadSignature
from typing import Optional
from posthog.models.utils import UUIDModel
from enum import Enum
import uuid


# class syntax
class PreferenceStatus(str, Enum):
    OPTED_IN = "OPTED_IN"
    OPTED_OUT = "OPTED_OUT"
    NO_PREFERENCE = "NO_PREFERENCE"

    @classmethod
    def choices(cls):
        return [(status.value, status.name) for status in cls]


class MessageCategory(UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(default=False)
    key = models.CharField(max_length=64)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    public_description = models.TextField(blank=True, default="")

    class Meta:
        unique_together = (
            "team",
            "key",
        )
        verbose_name_plural = "message categories"

    def __str__(self) -> str:
        return self.name


class MessageRecipientPreference(UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(default=False)
    identifier = models.CharField(max_length=512)
    preferences = models.JSONField(
        default=dict, help_text="Dictionary mapping MessageCategory UUIDs to preference statuses"
    )

    class Meta:
        unique_together = (
            "team",
            "identifier",
        )

    def __str__(self) -> str:
        return f"Preferences for {self.identifier}"

    def generate_preferences_token(self) -> str:
        """Generate a secure, time-limited token for accessing preferences"""
        signer = TimestampSigner()
        return signer.sign_object({"id": str(self.id), "identifier": self.identifier})

    @classmethod
    def validate_preferences_token(
        cls, token: str, max_age: int = 60 * 60 * 24 * 7
    ) -> tuple[Optional["MessageRecipientPreference"], str]:
        """
        Validate a preferences token and return the recipient if valid
        max_age defaults to 7 days
        Returns (recipient, error_message). If validation fails, recipient will be None
        """
        signer = TimestampSigner()
        try:
            data = signer.unsign_object(token, max_age=max_age)
            return cls.objects.get(id=uuid.UUID(data["id"]), identifier=data["identifier"]), ""
        except SignatureExpired:
            return None, "This link has expired. Please request a new one."
        except BadSignature:
            return None, "Invalid or tampered preferences link."
        except cls.DoesNotExist:
            return None, "Recipient not found."
        except Exception:
            return None, "An error occurred validating your preferences link."

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
