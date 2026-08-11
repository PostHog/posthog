from dataclasses import dataclass

from posthog.api.personal_api_key import PersonalAPIKeySerializer
from posthog.api.project_secret_api_key import roll_project_secret_api_key_and_notify
from posthog.models.oauth import find_oauth_access_token, find_oauth_refresh_token, revoke_oauth_session
from posthog.models.personal_api_key import find_personal_api_key
from posthog.models.project_secret_api_key import find_project_secret_api_key
from posthog.models.utils import (
    OAUTH_ACCESS_TOKEN_PREFIX,
    OAUTH_REFRESH_TOKEN_PREFIX,
    PERSONAL_API_KEY_PREFIX,
    SECRET_API_TOKEN_PREFIX,
    mask_key_value,
)
from posthog.tasks.email import send_oauth_token_exposed, send_personal_api_key_exposed

CANONICAL_PERSONAL_API_KEY = "personal_api_key"
CANONICAL_PROJECT_SECRET_API_KEY = "project_secret_api_key"
CANONICAL_OAUTH_ACCESS_TOKEN = "oauth_access_token"
CANONICAL_OAUTH_REFRESH_TOKEN = "oauth_refresh_token"


@dataclass(frozen=True, kw_only=True)
class RevocationResult:
    found: bool
    key_type: str | None


def _revoke_personal_api_key(token: str, more_info: str) -> bool:
    key_lookup = find_personal_api_key(token)
    if key_lookup is None:
        return False
    key, _ = key_lookup
    old_mask_value = key.mask_value
    serializer = PersonalAPIKeySerializer(instance=key)
    serializer.roll(key)
    send_personal_api_key_exposed(key.user.id, key.id, old_mask_value, more_info)
    return True


def _revoke_project_secret_api_key(token: str, more_info: str) -> bool:
    project_secret_api_key = find_project_secret_api_key(token)
    if project_secret_api_key is None:
        return False
    roll_project_secret_api_key_and_notify(project_secret_api_key, more_info)
    return True


def _revoke_oauth_access_token(token: str, more_info: str) -> bool:
    access_token = find_oauth_access_token(token)
    if access_token is None:
        return False
    user = access_token.user
    revoke_oauth_session(access_token=access_token)
    if user:
        send_oauth_token_exposed(user.id, "access", mask_key_value(token), more_info)
    return True


def _revoke_oauth_refresh_token(token: str, more_info: str) -> bool:
    refresh_token = find_oauth_refresh_token(token)
    if refresh_token is None:
        return False
    user = refresh_token.user
    revoke_oauth_session(refresh_token=refresh_token)
    if user:
        send_oauth_token_exposed(user.id, "refresh", mask_key_value(token), more_info)
    return True


_REVOKERS = {
    CANONICAL_PERSONAL_API_KEY: _revoke_personal_api_key,
    CANONICAL_PROJECT_SECRET_API_KEY: _revoke_project_secret_api_key,
    CANONICAL_OAUTH_ACCESS_TOKEN: _revoke_oauth_access_token,
    CANONICAL_OAUTH_REFRESH_TOKEN: _revoke_oauth_refresh_token,
}

# Every key type has a reserved prefix (posthog/models/utils.py) enforced at
# generation time. Auto-detect uses it to run exactly one lookup instead of trying
# every type in turn — a token matching no known prefix costs nothing beyond these
# string comparisons, instead of paying for a personal-API-key lookup's SHA-256 +
# two rounds of PBKDF2 (PERSONAL_API_KEY_MODES_TO_TRY) on every unrecognized string
# an anonymous caller submits.
#
# Team-level secret tokens (Team.secret_api_token) share SECRET_API_TOKEN_PREFIX
# with project secret API keys but are deliberately not in this map: unlike these
# four, a match there can't be auto-rotated on the spot
# (Team.rotate_secret_token_and_save needs a user to attribute the rotation to), so
# github.py handles that case itself as a fallback rather than through this shared,
# type-agnostic path.
_PREFIX_TO_CANONICAL_TYPE = {
    PERSONAL_API_KEY_PREFIX: CANONICAL_PERSONAL_API_KEY,
    SECRET_API_TOKEN_PREFIX: CANONICAL_PROJECT_SECRET_API_KEY,
    OAUTH_ACCESS_TOKEN_PREFIX: CANONICAL_OAUTH_ACCESS_TOKEN,
    OAUTH_REFRESH_TOKEN_PREFIX: CANONICAL_OAUTH_REFRESH_TOKEN,
}


def _detect_canonical_type(token: str) -> str | None:
    for prefix, canonical_type in _PREFIX_TO_CANONICAL_TYPE.items():
        if token.startswith(prefix):
            return canonical_type
    return None


def revoke_leaked_secret(token: str, key_type: str | None, more_info: str) -> RevocationResult:
    """Look up `token` as a leaked credential and revoke+notify on a match.

    If `key_type` is one of the CANONICAL_* constants, only that lookup runs.
    If `key_type` is None, the token's prefix determines which single lookup runs.
    """
    resolved_type = key_type if key_type is not None else _detect_canonical_type(token)
    if resolved_type is not None and _REVOKERS[resolved_type](token, more_info):
        return RevocationResult(found=True, key_type=resolved_type)
    return RevocationResult(found=False, key_type=None)
