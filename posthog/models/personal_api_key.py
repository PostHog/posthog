from typing import TYPE_CHECKING, Optional

from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q, QuerySet
from django.utils import timezone

from django_deprecate_fields import deprecate_field
from prometheus_client import Counter

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import EncryptionModeType, generate_random_token, hash_key_value

if TYPE_CHECKING:
    from posthog.models.organization import Organization

PERSONAL_API_KEY_MODES_TO_TRY: tuple[tuple[EncryptionModeType, Optional[int]], ...] = (
    ("sha256", None),  # Moved to simple hashing in 2024-02
    ("pbkdf2", 260000),  # This is the iteration count used by PostHog since the beginning of time.
    ("pbkdf2", 390000),  # This is the iteration count used briefly on some API keys.
)

LEGACY_PERSONAL_API_KEY_SALT = "posthog_personal_api_key"
LEGACY_HASH_PREFIX = f"{PBKDF2PasswordHasher.algorithm}$"

PERSONAL_API_KEY_AUTH_COUNTER = Counter(
    "personal_api_key_hash_mode_total",
    "Successful personal API key authentications by hash mode",
    labelnames=["hash_mode"],
)


class PersonalAPIKey(ModelActivityMixin, models.Model):
    id = models.CharField(primary_key=True, max_length=50, default=generate_random_token)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="personal_api_keys")
    label = models.CharField(max_length=40)
    description = models.TextField(null=True, blank=True, max_length=1000)
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
    scopes: ArrayField = ArrayField(models.CharField(max_length=100), default=list)
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
        secure_value = hash_key_value(token, mode=mode, legacy_salt=LEGACY_PERSONAL_API_KEY_SALT, iterations=iterations)
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


def get_organization_personal_api_keys(organization: "Organization") -> QuerySet[PersonalAPIKey]:
    """Personal API keys of org members that can access this organization or any of its projects.

    Includes fully unscoped keys (which can reach everything the owner can), keys explicitly scoped
    to this organization, and keys scoped to any of the organization's teams.
    """
    team_ids = list(organization.teams.values_list("id", flat=True))
    return (
        PersonalAPIKey.objects.filter(user__organization_membership__organization_id=organization.id)
        .filter(
            Q(scoped_organizations__contains=[str(organization.id)])
            | Q(scoped_teams__overlap=team_ids)
            | (
                (Q(scoped_organizations__isnull=True) | Q(scoped_organizations=[]))
                & (Q(scoped_teams__isnull=True) | Q(scoped_teams=[]))
            )
        )
        .select_related("user")
        .distinct()
    )
