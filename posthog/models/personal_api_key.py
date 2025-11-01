import hashlib
from typing import Literal, Optional

from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from django_deprecate_fields import deprecate_field

from posthog.models.activity_logging.model_activity import ModelActivityMixin

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


class PersonalAPIKey(ModelActivityMixin, models.Model):
    id = models.CharField(primary_key=True, max_length=50, default=generate_random_token)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="personal_api_keys")
    label = models.CharField(max_length=40)
    mask_value = models.CharField(max_length=11, editable=False, null=True)
    secure_value = models.CharField(
        unique=True,
        max_length=300,
        null=True,
        editable=False,
    )
    created_at = models.DateTimeField(default=timezone.now)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_rolled_at = models.DateTimeField(null=True, blank=True)
    scopes: ArrayField = ArrayField(models.CharField(max_length=100), null=True)
    scoped_teams: ArrayField = ArrayField(models.IntegerField(), null=True)
    scoped_organizations: ArrayField = ArrayField(models.CharField(max_length=100), null=True)

    # DEPRECATED: value is no longer persisted; use secure_value for hash of value
    value = deprecate_field(models.CharField(unique=True, max_length=50, editable=False, null=True, blank=True))
    # DEPRECATED: personal API keys are now specifically personal, without team affiliation
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.SET_NULL,
        related_name="personal_api_keys+",
        null=True,
        blank=True,
    )


def find_personal_api_key(token: str) -> tuple[PersonalAPIKey, str] | None:
    for mode, iterations in PERSONAL_API_KEY_MODES_TO_TRY:
        secure_value = hash_key_value(token, mode=mode, iterations=iterations)
        try:
            obj = (
                PersonalAPIKey.objects.select_related("user")
                .filter(user__is_active=True)
                .get(secure_value=secure_value)
            )
            return obj, mode

        except PersonalAPIKey.DoesNotExist:
            pass

    return None
