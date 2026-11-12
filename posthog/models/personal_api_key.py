import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Optional

from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q, QuerySet
from django.utils import timezone

from prometheus_client import Counter

from posthog.constants import AvailableFeature
from posthog.migration_helpers import deprecate_field
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import PERSONAL_API_KEY_PREFIX, EncryptionModeType, generate_random_token, hash_key_value

if TYPE_CHECKING:
    from posthog.models.organization import Organization
    from posthog.models.user import User

HashMode = tuple[EncryptionModeType, Optional[int]]

CURRENT_PERSONAL_API_KEY_MODE: HashMode = ("sha256", None)  # Moved to simple hashing in 2024-02
PERSONAL_API_KEY_MODES_TO_TRY: tuple[HashMode, ...] = (
    CURRENT_PERSONAL_API_KEY_MODE,
    ("pbkdf2", 260000),  # This is the iteration count used by PostHog since the beginning of time.
    ("pbkdf2", 390000),  # This is the iteration count used briefly on some API keys.
)

LEGACY_PERSONAL_API_KEY_SALT = "posthog_personal_api_key"
LEGACY_HASH_PREFIX = f"{PBKDF2PasswordHasher.algorithm}$"

DEFAULT_MAX_PERSONAL_API_KEYS = 10

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
    expires_at = models.DateTimeField(null=True, blank=True)
    scopes: ArrayField = ArrayField(models.CharField(max_length=100), default=list)
    scoped_teams: ArrayField = ArrayField(models.IntegerField(), null=True, blank=True)
    scoped_organizations: ArrayField = ArrayField(models.CharField(max_length=100), null=True, blank=True)

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

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= timezone.now()


def max_personal_api_keys_for_user(user: "User") -> int:
    """How many personal API keys the user may hold.

    A key is not bound to one organization, so the highest `personal_api_keys` limit across the
    user's organizations applies. Organizations without a numeric limit grant the default.
    """
    org_features = user.organization_memberships.values_list("organization__available_product_features", flat=True)
    limits = [
        feature.get("limit")
        for features in org_features
        for feature in features or []
        if feature and feature.get("key") == AvailableFeature.PERSONAL_API_KEYS
    ]
    return max([DEFAULT_MAX_PERSONAL_API_KEYS, *(limit for limit in limits if isinstance(limit, int))])


_LEGACY_PERSONAL_API_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def looks_like_legacy_personal_api_key(token: str) -> bool:
    """Personal API keys created before the phx_ prefix (2021-06-23, commit
    6c9bb2db0fb) are bare secrets.token_urlsafe(32) output: exactly 43 URL-safe
    base64 characters, no prefix. They're still valid today — PERSONAL_API_KEY_MODES_TO_TRY
    exists specifically to authenticate them via their legacy hash. This exact
    length+charset check keeps auto-detect's cost bound intact: only a token
    matching this precise shape reaches the expensive personal-key lookup,
    not every unrecognized string.
    """
    return bool(_LEGACY_PERSONAL_API_KEY_PATTERN.match(token))


def personal_api_key_modes_to_try(token: str) -> tuple[HashMode, ...]:
    """Keys issued before 2024-02 can still carry a pbkdf2 hash, and those keys are either
    phx_-prefixed or legacy-shaped. Any other token can only match sha256, so it skips the
    pbkdf2 rounds that make a failed lookup cost hundreds of milliseconds.
    """
    if token.startswith(PERSONAL_API_KEY_PREFIX) or looks_like_legacy_personal_api_key(token):
        return PERSONAL_API_KEY_MODES_TO_TRY
    return (CURRENT_PERSONAL_API_KEY_MODE,)


def find_personal_api_key(token: str) -> tuple[PersonalAPIKey, str] | None:
    for mode, iterations in personal_api_key_modes_to_try(token):
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


def get_organization_ids_in_key_scope(
    key: PersonalAPIKey, team_organization_ids: Mapping[int, str]
) -> frozenset[str] | None:
    """Return the organizations that the key's scope lists allow, or None when the key has no scope lists.

    Authentication applies each non-empty list as its own limit, so a scoped team counts only when its
    organization also passes the organization list. `team_organization_ids` maps a team to its organization.
    A scoped team that is missing from it does not count.
    """
    scoped_organization_ids = frozenset(key.scoped_organizations or [])
    if not key.scoped_teams:
        return scoped_organization_ids or None
    return frozenset(
        organization_id
        for team_id in key.scoped_teams
        if (organization_id := team_organization_ids.get(team_id)) is not None
        and (not scoped_organization_ids or organization_id in scoped_organization_ids)
    )


def get_organization_personal_api_keys(organization: "Organization") -> QuerySet[PersonalAPIKey]:
    """Return the personal API keys of org members that can authenticate to this organization or its projects.

    The scope filters are the SQL form of `get_organization_ids_in_key_scope`. The other filters drop
    expired keys, keys without scopes, keys of inactive users, and member keys that the organization blocks.
    `APIScopePermission` applies that block only while the organization has the security settings feature,
    so this filter has the same condition.
    """
    # organization.py imports this module, so a module-level import is circular.
    from posthog.models.organization import OrganizationMembership

    membership = Q(user__organization_membership__organization_id=organization.id)
    if not organization.members_can_use_personal_api_keys and organization.is_feature_available(
        AvailableFeature.ORGANIZATION_SECURITY_SETTINGS
    ):
        membership &= Q(user__organization_membership__level__gte=OrganizationMembership.Level.ADMIN)
    team_ids = list(organization.teams.values_list("id", flat=True))
    return (
        PersonalAPIKey.objects.filter(membership, user__is_active=True)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .exclude(scopes=[])
        .filter(
            Q(scoped_organizations__isnull=True)
            | Q(scoped_organizations=[])
            | Q(scoped_organizations__contains=[str(organization.id)])
        )
        .filter(Q(scoped_teams__isnull=True) | Q(scoped_teams=[]) | Q(scoped_teams__overlap=team_ids))
        .select_related("user")
        .distinct()
    )
