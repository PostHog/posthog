from enum import Enum
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

    @property
    def scopes_list(self) -> list[str]:
        return self.scopes.split(",") if self.scopes else []


## API Scopes
# These are the scopes that are used to define the permissions of the API tokens.
# Not every model needs a scope - it should more be for top-level things
# Typically each object should have `read` and `write` scopes, but some objects may have more specific scopes


class APIScopeObjectOrNotSupported(Enum):
    NOT_SUPPORTED = "not_supported"

    ACTION = "action"
    ACTIVITY_LOG = "activity_log"
    ANNOTATION = "annotation"
    BATCH_EXPORT = "batch_export"
    COHORT = "cohort"
    DASHBOARD = "dashboard"
    EARLY_ACCESS_FEATURE = "early_access_feature"
    EVENT_DEFINITION = "event_definition"
    EXPERIMENT = "experiment"
    EXPORT = "export"
    FEATURE_FLAG = "feature_flag"
    GROUP = "group"
    INSIGHT = "insight"
    QUERY = "query"
    NOTEBOOK = "notebook"
    ORGANIZATION = "organization"
    ORGANIZATION_MEMBER = "organization_member"
    PERSON = "person"
    PLUGIN = "plugin"
    PROPERTY_DEFINITION = "property_definition"
    SESSION_RECORDING = "session_recording"
    SESSION_RECORDING_PLAYLIST = "session_recording_playlist"
    SHARING_CONFIGURATION = "sharing_configuration"
    SUBSCRIPTION = "subscription"
    SURVEY = "survey"
    TEAM = "team"
    USER = "user"
    DATA_WAREHOUSE_TABLE = "data_warehouse_table"
    SCHEDULED_CHANGE = "scheduled_change"
