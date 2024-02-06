from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.db import models
from django.utils import timezone

from .utils import generate_random_token

# Fixed iteration count for PBKDF2PasswordHasher hasher.
# This is the iteration count used by PostHog since the beginning of time.
# Changing this would break all existing personal API keys.
PERSONAL_API_KEY_ITERATIONS = 260000

PERSONAL_API_KEY_ITERATIONS_TO_TRY = (
    PERSONAL_API_KEY_ITERATIONS,
    390000,  # This is the iteration count used briefly on some API keys.
)

# A constant salt is not nearly as good as user-specific, but we must be able to look up a personal API key
# by itself. Some salt is slightly better than none though.
PERSONAL_API_KEY_SALT = "posthog_personal_api_key"


def hash_key_value(value: str, iterations: int = PERSONAL_API_KEY_ITERATIONS) -> str:
    hasher = PBKDF2PasswordHasher()
    return hasher.encode(value, PERSONAL_API_KEY_SALT, iterations=iterations)


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
    scopes: models.CharField = models.CharField(max_length=1000, null=True, blank=True)

    # DEPRECATED: personal API keys are now specifically personal, without team affiliation
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.SET_NULL,
        related_name="personal_api_keys+",
        null=True,
        blank=True,
    )
