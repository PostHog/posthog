import hashlib
from typing import Optional, Literal

from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.db import models
from django.utils import timezone

from .utils import generate_random_token

ModeType = Literal["sha256", "pbkdf2"]
PERSONAL_API_KEY_MODES_TO_TRY: tuple[tuple[ModeType, Optional[int]], ...] = (
    ("sha256", None),  # Moved to simple hashing in 2024-02
    ("pbkdf2", 260000),  # This is the iteration count used by PostHog since the beginning of time.
    ("pbkdf2", 390000),  # This is the iteration count used briefly on some API keys.
)

LEGACY_PERSONAL_API_KEY_SALT = "posthog_personal_api_key"


def hash_key_value(value: str, mode: ModeType = "sha256", iterations: Optional[int] = None) -> str:
    if mode == "pbkdf2":
        if not iterations:
            raise ValueError("Iterations must be provided when using legacy PBKDF2 mode")

        hasher = PBKDF2PasswordHasher()
        return hasher.encode(value, LEGACY_PERSONAL_API_KEY_SALT, iterations=iterations)

    if iterations:
        raise ValueError("Iterations must not be provided when using simple hashing mode")

    # Inspiration on why no salt:
    # https://github.com/jazzband/django-rest-knox/issues/188
    value = hashlib.sha256(value.encode()).hexdigest()
    return f"sha256${value}"  # Following format from Django's PBKDF2PasswordHasher


class PersonalAPIKey(models.Model):
    id: models.CharField = models.CharField(primary_key=True, max_length=50, default=generate_random_token)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="personal_api_keys")
    label: models.CharField = models.CharField(max_length=40)
    value: models.CharField = models.CharField(unique=True, max_length=50, editable=False, null=True, blank=True)
    secure_value: models.CharField = models.CharField(
        unique=True,
        max_length=300,
        null=True,
        editable=False,
    )
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    last_used_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)

    # DEPRECATED: personal API keys are now specifically personal, without team affiliation
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.SET_NULL,
        related_name="personal_api_keys+",
        null=True,
        blank=True,
    )
