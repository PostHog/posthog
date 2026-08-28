import re
from typing import Literal

from posthog.api.personal_api_key import PersonalAPIKeySerializer
from posthog.api.project_secret_api_key import roll_project_secret_api_key_and_notify
from posthog.dataclasses import frozen
from posthog.models.oauth import find_oauth_access_token, find_oauth_refresh_token, revoke_oauth_token_session
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


@frozen
class RevocationResult:
    key_type: str | None

    @property
    def found(self) -> bool:
        return self.key_type is not None


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


def _revoke_oauth_token(token: str, more_info: str, *, kind: Literal["access", "refresh"]) -> bool:
    # Deliberately no expiry check on the access-token match: an already-expired token
    # can't authenticate on its own, but revoking still matters if the same exposure
    # also affects the paired refresh token (up to 30 days live). Gating this on
    # expiry would only block that revocation, not close any capability - both this
    # endpoint and github.py's webhook are triggerable by anyone holding a copy of a
    # token, dead or alive (a public GitHub commit gets scanned and reported the same
    # as an anonymous POST here), so there is no less-exposed path to gate in favor of.
    # The only real consequence of a match either way is forcing a re-authentication,
    # not a confidentiality or integrity loss.
    if kind == "access":
        access_token = find_oauth_access_token(token)
        if access_token is None:
            return False
        # Scoped to this one access/refresh token pair, not every session the user has
        # with the application - a leaked-token report is evidence about that one
        # token, not the user's other sessions. See revoke_oauth_token_session.
        revoke_oauth_token_session(access_token=access_token)
        user = access_token.user
    else:
        refresh_token = find_oauth_refresh_token(token)
        if refresh_token is None:
            return False
        revoke_oauth_token_session(refresh_token=refresh_token)
        user = refresh_token.user
    if user:
        send_oauth_token_exposed(user.id, kind, mask_key_value(token), more_info)
    return True


def _revoke_oauth_access_token(token: str, more_info: str) -> bool:
    return _revoke_oauth_token(token, more_info, kind="access")


def _revoke_oauth_refresh_token(token: str, more_info: str) -> bool:
    return _revoke_oauth_token(token, more_info, kind="refresh")


_REVOKERS = {
    CANONICAL_PERSONAL_API_KEY: _revoke_personal_api_key,
    CANONICAL_PROJECT_SECRET_API_KEY: _revoke_project_secret_api_key,
    CANONICAL_OAUTH_ACCESS_TOKEN: _revoke_oauth_access_token,
    CANONICAL_OAUTH_REFRESH_TOKEN: _revoke_oauth_refresh_token,
}

# Every key type issued today has a reserved prefix (posthog/models/utils.py) enforced
# at generation time. Auto-detect uses it to run exactly one lookup instead of trying
# every type in turn — a token matching no known prefix costs nothing beyond these
# string comparisons, instead of paying for a personal-API-key lookup's SHA-256 +
# two rounds of PBKDF2 (PERSONAL_API_KEY_MODES_TO_TRY) on every unrecognized string
# an anonymous caller submits.
#
# Personal API keys are the one exception: those issued before the prefix existed have
# none, so the map alone would leave the fleet's oldest keys unrevocable.
# _looks_like_legacy_personal_api_key covers them by shape instead. That widens what
# reaches the personal-key lookup — any 43-character URL-safe string qualifies,
# including legacy unprefixed Team.api_token values, which simply miss. That shape
# check only narrows *which* strings pay the expensive lookup, not how many times a
# caller can pay it: on the public endpoint, a caller can construct a matching string
# on purpose, so per-request cost is still bounded only by LeakedKeyReportThrottle's
# per-IP rate limit, not by this check.
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

# The non-personal-key prefixes above, re-exported so other prefix-based key-type checks
# (e.g. the admin key-search view in posthog/views.py) can stay in sync with this map
# instead of re-listing the same three prefixes by hand.
NON_PERSONAL_SECRET_PREFIXES = (
    SECRET_API_TOKEN_PREFIX,
    OAUTH_ACCESS_TOKEN_PREFIX,
    OAUTH_REFRESH_TOKEN_PREFIX,
)


_LEGACY_PERSONAL_API_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def _looks_like_legacy_personal_api_key(token: str) -> bool:
    """Personal API keys created before the phx_ prefix (2021-06-23, commit
    6c9bb2db0fb) are bare secrets.token_urlsafe(32) output: exactly 43 URL-safe
    base64 characters, no prefix. They're still valid today — PERSONAL_API_KEY_MODES_TO_TRY
    exists specifically to authenticate them via their legacy hash. This exact
    length+charset check keeps auto-detect's cost bound intact: only a token
    matching this precise shape reaches the expensive personal-key lookup,
    not every unrecognized string.
    """
    return bool(_LEGACY_PERSONAL_API_KEY_PATTERN.match(token))


def _detect_canonical_type(token: str) -> str | None:
    for prefix, canonical_type in _PREFIX_TO_CANONICAL_TYPE.items():
        if token.startswith(prefix):
            return canonical_type
    if _looks_like_legacy_personal_api_key(token):
        return CANONICAL_PERSONAL_API_KEY
    return None


def revoke_leaked_secret(token: str, key_type: str | None, more_info: str) -> RevocationResult:
    """Look up `token` as a leaked credential and revoke+notify on a match.

    If `key_type` is one of the CANONICAL_* constants, only that lookup runs.
    If `key_type` is None, the token's prefix determines which single lookup runs.
    """
    resolved_type = key_type if key_type is not None else _detect_canonical_type(token)
    if resolved_type is not None and _REVOKERS[resolved_type](token, more_info):
        return RevocationResult(key_type=resolved_type)
    return RevocationResult(key_type=None)
