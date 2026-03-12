from django.db.models import QuerySet
from django.utils import timezone

from posthog.models import User
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal, mask_key_value
from posthog.scopes import API_SCOPE_ACTIONS, API_SCOPE_OBJECTS

MAX_API_KEYS_PER_USER = 10


def validate_scopes(scopes: list[str]) -> list[str]:
    """Validate scope strings against API_SCOPE_OBJECTS x API_SCOPE_ACTIONS.

    Raises ValueError on invalid scope.
    """
    for scope in scopes:
        if scope == "*":
            continue

        scope_parts = scope.split(":")
        if len(scope_parts) != 2 or scope_parts[0] not in API_SCOPE_OBJECTS or scope_parts[1] not in API_SCOPE_ACTIONS:
            raise ValueError(f"Invalid scope: {scope}")

    return scopes


def create_personal_api_key(
    user: User,
    label: str,
    scopes: list[str],
    scoped_teams: list[int] | None = None,
    scoped_organizations: list[str] | None = None,
) -> tuple[PersonalAPIKey, str]:
    """Create a key and return (model, raw_value).

    raw_value is the only time the unhashed secret is available.
    """
    count = PersonalAPIKey.objects.filter(user=user).count()
    if count >= MAX_API_KEYS_PER_USER:
        raise ValueError(f"Limit of {MAX_API_KEYS_PER_USER} personal API keys reached.")

    value = generate_random_token_personal()
    secure_value = hash_key_value(value)
    mask = mask_key_value(value)
    key = PersonalAPIKey.objects.create(
        user=user,
        label=label,
        secure_value=secure_value,
        mask_value=mask,
        scopes=scopes,
        scoped_teams=scoped_teams,
        scoped_organizations=scoped_organizations,
    )
    return key, value


def roll_personal_api_key(key: PersonalAPIKey) -> tuple[PersonalAPIKey, str]:
    """Roll a key's secret. Returns (updated model, new raw_value)."""
    value = generate_random_token_personal()
    key.secure_value = hash_key_value(value)
    key.mask_value = mask_key_value(value)
    key.last_rolled_at = timezone.now()
    key.save(update_fields=["secure_value", "mask_value", "last_rolled_at"])
    return key, value


def list_personal_api_keys(user: User) -> QuerySet[PersonalAPIKey]:
    """Return all keys for a user, ordered by created_at desc."""
    return PersonalAPIKey.objects.filter(user=user).order_by("-created_at")
