from django.db import models
from django.core.validators import EmailValidator
from django.core.signing import TimestampSigner, SignatureExpired, BadSignature
from typing import Optional


class MessageCategory(models.Model):
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    is_system_category = models.BooleanField(default=False, help_text="System categories cannot be deleted")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "message categories"

    def __str__(self) -> str:
        return self.name


class RecipientIdentifier(models.Model):
    IDENTIFIER_TYPE_CHOICES = [
        ("email", "Email Address"),
        ("phone", "Phone Number"),
        ("device", "Device ID"),
        ("push", "Push Token"),
        ("browser", "Browser Token"),
        ("slack", "Slack User ID"),
    ]

    identifier = models.CharField(max_length=512)
    type = models.CharField(max_length=32, choices=IDENTIFIER_TYPE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [["identifier", "type"]]
        indexes = [
            models.Index(fields=["identifier", "type"]),
            models.Index(fields=["type"]),
        ]

    def __str__(self) -> str:
        return f"{self.identifier} ({self.type})"

    def clean(self):
        if self.type == "email":
            EmailValidator()(self.identifier)

    def generate_preferences_token(self) -> str:
        """Generate a secure, time-limited token for accessing preferences"""
        signer = TimestampSigner()
        return signer.sign_object({"id": self.id, "identifier": self.identifier, "type": self.type})

    @classmethod
    def validate_preferences_token(
        cls, token: str, max_age: int = 60 * 60 * 24 * 7
    ) -> tuple[Optional["RecipientIdentifier"], str]:
        """
        Validate a preferences token and return the recipient if valid
        max_age defaults to 7 days
        Returns (recipient, error_message). If validation fails, recipient will be None
        """
        signer = TimestampSigner()
        try:
            data = signer.unsign_object(token, max_age=max_age)
            return cls.objects.get(id=data["id"], identifier=data["identifier"], type=data["type"]), ""
        except SignatureExpired:
            return None, "This link has expired. Please request a new one."
        except BadSignature:
            return None, "Invalid or tampered preferences link."
        except cls.DoesNotExist:
            return None, "Recipient not found."
        except Exception:
            return None, "An error occurred validating your preferences link."


class MessagePreference(models.Model):
    recipient = models.ForeignKey("RecipientIdentifier", on_delete=models.CASCADE, related_name="preferences")
    category = models.ForeignKey("MessageCategory", on_delete=models.CASCADE, related_name="preferences")
    opted_in = models.BooleanField(null=True, help_text="Null means no explicit preference set")
    last_updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who last updated this preference",
    )

    class Meta:
        unique_together = [["recipient", "category"]]
        indexes = [
            models.Index(fields=["recipient", "category"]),
            models.Index(fields=["category"]),
            models.Index(fields=["opted_in"]),
        ]

    def __str__(self) -> str:
        status = "opted in" if self.opted_in else "opted out" if self.opted_in is False else "no preference"
        return f"{self.recipient} - {self.category}: {status}"

    @classmethod
    def get_preference(cls, identifier: str, identifier_type: str, category_key: str) -> Optional["MessagePreference"]:
        """
        Helper method to easily get preferences for a recipient and category
        Returns None if no explicit preference is set
        """
        try:
            return cls.objects.select_related("recipient", "category").get(
                recipient__identifier=identifier, recipient__type=identifier_type, category__key=category_key
            )
        except cls.DoesNotExist:
            return None

    @classmethod
    def set_preference(
        cls,
        identifier: str,
        identifier_type: str,
        category_key: str,
        opted_in: bool,
        updated_by=None,
    ) -> "MessagePreference":
        """
        Helper method to easily set preferences for a recipient and category
        Creates or updates the recipient and preference as needed
        """
        recipient, _ = RecipientIdentifier.objects.get_or_create(identifier=identifier, type=identifier_type)
        category = MessageCategory.objects.get(key=category_key)

        preference, _ = cls.objects.get_or_create(
            recipient=recipient,
            category=category,
            defaults={
                "opted_in": opted_in,
                "updated_by": updated_by,
            },
        )

        if not _:  # If preference existed, update it
            preference.opted_in = opted_in
            preference.updated_by = updated_by
            preference.save()

        return preference
