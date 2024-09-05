from typing import Optional, Literal, get_args
import hashlib

from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.contrib.postgres.fields import ArrayField
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


def mask_key_value(value: str) -> str:
    """Turn 'phx_123456abcd' into 'phx_...abcd'."""
    return f"{value[:4]}...{value[-4:]}"


class PersonalAPIKey(models.Model):
    id = models.CharField(primary_key=True, max_length=50, default=generate_random_token)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="personal_api_keys")
    label = models.CharField(max_length=40)
    value = models.CharField(unique=True, max_length=50, editable=False, null=True, blank=True)
    mask_value = models.CharField(max_length=11, editable=False, null=True)
    secure_value = models.CharField(
        unique=True,
        max_length=300,
        null=True,
        editable=False,
    )
    created_at = models.DateTimeField(default=timezone.now)
    last_used_at = models.DateTimeField(null=True, blank=True)
    scopes: ArrayField = ArrayField(models.CharField(max_length=100), null=True)
    scoped_teams: ArrayField = ArrayField(models.IntegerField(), null=True)
    scoped_organizations: ArrayField = ArrayField(models.CharField(max_length=100), null=True)

    # DEPRECATED: personal API keys are now specifically personal, without team affiliation
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.SET_NULL,
        related_name="personal_api_keys+",
        null=True,
        blank=True,
    )


## API Scopes
# These are the scopes that are used to define the permissions of the API tokens.
# Not every model needs a scope - it should more be for top-level things
# Typically each object should have `read` and `write` scopes, but some objects may have more specific scopes

# WARNING: Make sure to keep in sync with the frontend!
APIScopeObject = Literal[
    "action",
    "activity_log",
    "annotation",
    "batch_export",
    "cohort",
    "dashboard",
    "dashboard_template",
    "early_access_feature",
    "event_definition",
    "experiment",
    "export",
    "feature_flag",
    "group",
    "insight",
    "query",  # Covers query and events endpoints
    "notebook",
    "organization",
    "organization_member",
    "person",
    "plugin",
    "project",
    "property_definition",
    "session_recording",
    "session_recording_playlist",
    "sharing_configuration",
    "subscription",
    "survey",
    "user",
    "webhook",
]

APIScopeActions = Literal[
    "read",
    "write",
]

APIScopeObjectOrNotSupported = Literal[
    APIScopeObject,
    "INTERNAL",
]


API_SCOPE_OBJECTS: tuple[APIScopeObject, ...] = get_args(APIScopeObject)
API_SCOPE_ACTIONS: tuple[APIScopeActions, ...] = get_args(APIScopeActions)
