"""
Gateway credential HyperCache — projection for the Go ai-gateway's auth path (RFC #1103).

One blob per phs_ project secret key / pha_ OAuth token, keyed by the credential's hash
so the secret never sits in a Redis key. Public phc_ project tokens can't dispatch.

    Key: cache/team_tokens_hashed/<sha256$hex>/team_metadata/gateway_credential.json
    Body: {team_id, project_token, scopes, billing_mode, revoked_at, overspend_allowance_usd?}

The hash matches Django's hash_key_value(token, mode="sha256") = "sha256$"+hex, which the
gateway derives identically. A credential holding llm_gateway:read attributes to its team
directly (no per-gateway entity); team_id is the billing-attribution dimension. project_token
is the team's phc_ key, carried only so the gateway can stamp the $ai_generation envelope —
it never authorizes dispatch; the phs_/pha_ secret does. The gateway fails closed on a
missing field, so a blob is written only for a fully-resolvable credential and cleared
otherwise. Redis-only: a ~1h OAuth token would outlive an S3 lifecycle and resurrect on a
cold Redis.
"""

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import OperationalError
from django.utils import timezone

import structlog

from posthog.caching.ai_gateway_redis_cache import AI_GATEWAY_DEDICATED_CACHE_ALIAS
from posthog.models.oauth import OAuthAccessToken
from posthog.models.organization import OrganizationMembership
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import SHA256_HASH_PREFIX, hash_key_value
from posthog.rbac.user_access_control import UserAccessControl, ordered_access_levels
from posthog.redis import get_client
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType

logger = structlog.get_logger(__name__)

GATEWAY_CREDENTIAL_REQUIRED_SCOPE = "llm_gateway:read"

# billing_mode is provisional — the gateway treats it as opaque pass-through and
# does not enforce it yet. Open: whether it is ever non-internal.
GATEWAY_CREDENTIAL_BILLING_MODE = "internal"

# Minimum project access level a user needs for the bound team. The project read
# level is the second-highest in the member ladder (none < member < admin).
_PROJECT_READ_ACCESS_LEVEL = ordered_access_levels("project")[-2]

GATEWAY_CREDENTIAL_CACHE_TTL = int(os.environ.get("GATEWAY_CREDENTIAL_CACHE_TTL", str(60 * 60 * 24 * 7)))
GATEWAY_CREDENTIAL_CACHE_MISS_TTL = int(os.environ.get("GATEWAY_CREDENTIAL_CACHE_MISS_TTL", str(60 * 60 * 24)))

# Caps the secret-key blob TTL so a signal-bypassing removal (e.g. .update())
# self-heals in hours, not the 7-day default. Must stay above the hourly refresh.
GATEWAY_CREDENTIAL_SECRET_KEY_CACHE_TTL = int(
    os.environ.get("GATEWAY_CREDENTIAL_SECRET_KEY_CACHE_TTL", str(60 * 60 * 6))
)

GATEWAY_CREDENTIAL_FIELDS = [
    "team_id",
    "project_token",
    "scopes",
    "billing_mode",
    "revoked_at",
]

# Overspend allowance wire contract (gateway-defined, internal/auth/gateway_credential.go):
# fixed-point USD string, 6dp, present only when set. Out-of-range/malformed clamps to 0 there,
# so we validate at the write surfaces instead of relying on the clamp.
OVERSPEND_ALLOWANCE_KEY = "overspend_allowance_usd"
OVERSPEND_ALLOWANCE_QUANTUM = Decimal("0.000001")
OVERSPEND_ALLOWANCE_MIN_USD = Decimal(0)
OVERSPEND_ALLOWANCE_MAX_USD = Decimal(10000)


def format_overspend_allowance_usd(value: Decimal) -> str:
    """Fixed-point 6dp string for the wire. `:f` avoids scientific notation, which the
    gateway's decimal parser can't read."""
    return f"{value.quantize(OVERSPEND_ALLOWANCE_QUANTUM):f}"


def validate_overspend_allowance_usd(value: Decimal) -> Decimal:
    """Quantize to 6dp; raise ValueError outside [0, 10000] or beyond 6dp. Callers map to
    their own error type."""
    if not value.is_finite():
        raise ValueError("overspend allowance must be a finite number")
    if value < OVERSPEND_ALLOWANCE_MIN_USD or value > OVERSPEND_ALLOWANCE_MAX_USD:
        raise ValueError(
            f"overspend allowance must be between {OVERSPEND_ALLOWANCE_MIN_USD} and {OVERSPEND_ALLOWANCE_MAX_USD} USD"
        )
    exponent = value.as_tuple().exponent  # int for any finite Decimal
    if isinstance(exponent, int) and -exponent > 6:
        raise ValueError("overspend allowance supports at most 6 decimal places")
    return value.quantize(OVERSPEND_ALLOWANCE_QUANTUM)


Credential = ProjectSecretAPIKey | OAuthAccessToken


class _RefreshMemo:
    """Per-run memo for the batch refresh: caches the per-(org, user) / (team, user) OAuth
    auth checks so a full re-projection does O(distinct users) lookups, not O(credentials).
    Single-credential callers pass no memo and are unaffected."""

    def __init__(self) -> None:
        self._memberships: dict[tuple[Any, Any], Any] = {}
        self._access: dict[tuple[Any, Any], bool] = {}
        self._teams: dict[Any, Team | None] = {}
        self._org_roots: dict[Any, int | None] = {}

    def membership(self, organization_id: Any, user_id: Any, load: Callable[[], Any]) -> Any:
        key = (organization_id, user_id)
        if key not in self._memberships:
            self._memberships[key] = load()
        return self._memberships[key]

    def access(self, team_id: Any, user_id: Any, load: Callable[[], bool]) -> bool:
        key = (team_id, user_id)
        if key not in self._access:
            self._access[key] = load()
        return self._access[key]

    def team(self, team_id: Any, load: Callable[[], "Team | None"]) -> "Team | None":
        if team_id not in self._teams:
            self._teams[team_id] = load()
        return self._teams[team_id]

    def org_root(self, organization_id: Any, load: Callable[[], int | None]) -> int | None:
        if organization_id not in self._org_roots:
            self._org_roots[organization_id] = load()
        return self._org_roots[organization_id]


def credential_hash(credential: Credential) -> str | None:
    """The sha256$<hex> cache-key hash for a credential.

    ProjectSecretAPIKey.secure_value already stores hash_key_value(token); OAuth
    keeps the plaintext token, so hash it the same way (its token_checksum is bare
    hex, which would not match the gateway's sha256$-prefixed derivation).
    """
    if isinstance(credential, ProjectSecretAPIKey):
        return credential.secure_value
    return hash_key_value(credential.token, mode="sha256")


def credential_has_gateway_scope(credential: Credential) -> bool:
    """Whether the credential literally holds llm_gateway:read.

    Literal only — a "*" wildcard must not subsume this privileged scope (RFC #1103);
    the gateway rejects a "*" blob and the legacy wildcard is being retired (#60342).
    """
    if isinstance(credential, ProjectSecretAPIKey):
        return GATEWAY_CREDENTIAL_REQUIRED_SCOPE in (credential.scopes or [])
    return GATEWAY_CREDENTIAL_REQUIRED_SCOPE in credential.scope.split()


def _org_root_team_id(organization_id: Any) -> int | None:
    """An organization's single project-root team, or None when absent/ambiguous.

    An OAuth app is org-scoped, so it attributes to the org's root team. Resolve only when
    exactly one root exists (fetch 2 to detect ambiguity) — fail closed otherwise."""
    if not organization_id:
        return None
    roots = list(
        Team.objects.filter(organization_id=organization_id, parent_team_id__isnull=True).values_list("id", flat=True)[
            :2
        ]
    )
    return roots[0] if len(roots) == 1 else None


def _team_by_id(team_id: int, memo: "_RefreshMemo | None") -> "Team | None":
    def load() -> "Team | None":
        return Team.objects.filter(pk=team_id).first()

    return memo.team(team_id, load) if memo else load()


def _team_for_credential(credential: Credential, memo: "_RefreshMemo | None" = None) -> "Team | None":
    """The team a credential attributes to (no per-gateway entity).

    A secret key attributes to its canonical (project-root) team; an OAuth token to its
    application's org root team. Returns None when the team can't be resolved unambiguously.
    """
    if isinstance(credential, ProjectSecretAPIKey):
        team_id: int | None = credential.team.parent_team_id or credential.team_id
    elif credential.application is not None:
        org_id = credential.application.organization_id
        team_id = memo.org_root(org_id, lambda: _org_root_team_id(org_id)) if memo else _org_root_team_id(org_id)
    else:
        team_id = None
    if team_id is None:
        return None
    return _team_by_id(team_id, memo)


def _ttl_for_credential(credential: Credential) -> float:
    """Seconds the blob may live. OAuth: remaining token lifetime from one now() read (may
    be <=0 if it just expired → caller clears instead of writing). Secret keys never expire,
    so cap them at a short TTL the hourly refresh keeps warm."""
    if isinstance(credential, OAuthAccessToken):
        return (credential.expires - timezone.now()).total_seconds()
    return GATEWAY_CREDENTIAL_SECRET_KEY_CACHE_TTL


def _oauth_authorization_ok(credential: OAuthAccessToken, team: Any, team_id: int, memo: "_RefreshMemo | None") -> bool:
    """Authorization checks that only apply to an OAuth credential.

    OAuth tokens carry a user, an expiry, and scoped_* narrowing the gateway can't
    see — all enforced here, since the gateway authenticates from the cached blob
    alone (and the hourly refresh re-checks). Returns False to fail closed.
    """
    user = credential.user
    if user is None or not user.is_active:
        return False
    if credential.application_id is None:
        return False
    if credential.expires <= timezone.now():
        return False

    # scoped_* narrows below the user's membership. team_id is the gateway's canonical
    # (project-root) team, so a token scoped only to a child env fails closed here.
    if credential.scoped_teams and team_id not in credential.scoped_teams:
        return False
    if credential.scoped_organizations and str(team.organization_id) not in credential.scoped_organizations:
        return False

    # scoped_organizations is a static ceiling that doesn't track membership changing.
    def _load_membership() -> Any:
        return (
            OrganizationMembership.objects.select_related("organization")
            .filter(organization_id=team.organization_id, user_id=user.id)
            .first()
        )

    membership = memo.membership(team.organization_id, user.id, _load_membership) if memo else _load_membership()
    if membership is None:
        return False

    # Project RBAC can revoke project access without touching org membership.
    # check_access_level_for_object default-allows admins/creators/no-AC-feature orgs,
    # so this only fails closed on an explicit revocation.
    def _load_access() -> bool:
        return UserAccessControl(user=user, team=team).check_access_level_for_object(
            team, required_level=_PROJECT_READ_ACCESS_LEVEL
        )

    return memo.access(team_id, user.id, _load_access) if memo else _load_access()


def _policy_for_credential(
    credential: Credential, memo: "_RefreshMemo | None" = None
) -> dict[str, Any] | HyperCacheStoreMissing:
    """Project a credential into the wire blob, or signal a clear.

    The credential's team (not a user's current team) is the source of truth for the billed
    team. Fails closed on missing scope, an unresolvable team, a team with no token, or — for
    OAuth — the user/expiry/scope/membership/RBAC checks. A project secret key has no user, so
    scope + resolvable-team + team-has-token is sufficient.
    """
    if not credential_has_gateway_scope(credential):
        return HyperCacheStoreMissing()

    team = _team_for_credential(credential, memo)
    if team is None:
        return HyperCacheStoreMissing()

    project_token = team.api_token
    if not project_token:
        return HyperCacheStoreMissing()

    if isinstance(credential, OAuthAccessToken) and not _oauth_authorization_ok(credential, team, team.id, memo):
        return HyperCacheStoreMissing()

    policy: dict[str, Any] = {
        "team_id": team.id,
        "project_token": project_token,
        "scopes": [GATEWAY_CREDENTIAL_REQUIRED_SCOPE],
        "billing_mode": GATEWAY_CREDENTIAL_BILLING_MODE,
        "revoked_at": None,
    }

    # Omit when null so the gateway uses its default; an explicit 0 disables the allowance.
    allowance = team.llm_gateway_overspend_allowance_usd
    if allowance is not None:
        policy[OVERSPEND_ALLOWANCE_KEY] = format_overspend_allowance_usd(allowance)

    return policy


def _resolve_credential(hash_key: str) -> Credential | None:
    """Reverse a cache-key hash back to its credential (Django-side reads only;
    the gateway never calls Django). ProjectSecretAPIKey.secure_value stores the
    prefixed hash directly; OAuth.token_checksum is the bare hex, so strip the prefix."""
    secret_key = ProjectSecretAPIKey.objects.select_related("team").filter(secure_value=hash_key).first()
    if secret_key is not None:
        return secret_key
    if hash_key.startswith(SHA256_HASH_PREFIX):
        checksum = hash_key[len(SHA256_HASH_PREFIX) :]
        return OAuthAccessToken.objects.select_related("user", "application").filter(token_checksum=checksum).first()
    return None


def _load_gateway_credential(hash_key: KeyType) -> dict[str, Any] | HyperCacheStoreMissing:
    # Narrow except clause for the same reason as the team analog: only a genuine
    # miss or a transient DB error should write a negative entry; a bug must
    # propagate so the next read retries instead of 401ing for the miss TTL.
    if not isinstance(hash_key, str):
        return HyperCacheStoreMissing()
    try:
        credential = _resolve_credential(hash_key)
        if credential is None:
            return HyperCacheStoreMissing()
        return _policy_for_credential(credential)
    except OperationalError as e:
        logger.exception("Database error loading gateway credential", error_type=type(e).__name__)
        return HyperCacheStoreMissing()


# Write-only from Django (the Go gateway reads Redis directly). Don't call
# get_from_cache — its lazy-fill ignores _ttl_for_credential and would write the 7-day
# default, defeating the secret-key cap. load_fn exists only because HyperCache requires one.
gateway_credential_hypercache = HyperCache(
    namespace="team_metadata",
    value="gateway_credential.json",
    hashed_credential_based=True,
    load_fn=_load_gateway_credential,
    cache_ttl=GATEWAY_CREDENTIAL_CACHE_TTL,
    cache_miss_ttl=GATEWAY_CREDENTIAL_CACHE_MISS_TTL,
    cache_alias=(AI_GATEWAY_DEDICATED_CACHE_ALIAS if AI_GATEWAY_DEDICATED_CACHE_ALIAS in settings.CACHES else None),
)


def project_gateway_credential(credential: Credential, memo: "_RefreshMemo | None" = None) -> None:
    """Write (or clear) the credential's policy blob from current DB state."""
    cache_hash = credential_hash(credential)
    if not cache_hash:
        return

    policy = _policy_for_credential(credential, memo)
    if isinstance(policy, HyperCacheStoreMissing):
        gateway_credential_hypercache.delete_cache_entry(cache_hash, kinds=["redis"])
        return

    ttl = _ttl_for_credential(credential)
    if ttl <= 0:  # OAuth token expired since the policy check — clear, don't write a 1s blob
        gateway_credential_hypercache.delete_cache_entry(cache_hash, kinds=["redis"])
        return

    # Floor at 1s so a sub-second-but-valid token isn't written with timeout=0,
    # which Django treats as evict-immediately.
    gateway_credential_hypercache.set_cache_value_redis_only(cache_hash, policy, ttl=max(1, int(ttl)))


def clear_gateway_credential(credential_or_hash: Credential | str) -> None:
    cache_hash = credential_or_hash if isinstance(credential_or_hash, str) else credential_hash(credential_or_hash)
    if not cache_hash:
        return
    gateway_credential_hypercache.delete_cache_entry(cache_hash, kinds=["redis"])


def refresh_all_gateway_credentials() -> int:
    """Re-project every credential currently granted llm_gateway:read, keeping entries warm.

    Forward-only (the cache key is a one-way hash); signals and the per-OAuth TTL handle
    removal. The team resolution and the per-OAuth membership/RBAC checks are memoized by team /
    (org, user) / (team, user) so the run does O(distinct teams/users) lookups, and .iterator()
    keeps the working set flat. The secret-key scopes lookup rides the projectsecretapikey_scopes_gin
    index; the OAuth scope regex rides the oauthaccesstoken_scope_trgm trigram GIN index.
    """
    now = timezone.now()
    memo = _RefreshMemo()
    querysets = (
        ProjectSecretAPIKey.objects.select_related("team").filter(scopes__contains=[GATEWAY_CREDENTIAL_REQUIRED_SCOPE]),
        OAuthAccessToken.objects.select_related("user", "application").filter(
            scope__iregex=r"(^|\s)llm_gateway:read(\s|$)",
            user__is_active=True,
            application_id__isnull=False,
            expires__gt=now,
        ),
    )

    count = 0
    for queryset in querysets:
        for credential in queryset.iterator(chunk_size=1000):
            project_gateway_credential(credential, memo)
            count += 1

    return count


# Gateway-owned Valkey hash (credential sha256$<hex> -> unix-second last-used),
# written by the gateway. Wire contract: must match internal/lastused.ValkeyKey.
GATEWAY_CREDENTIAL_LAST_USED_KEY = "ai-gateway:cred-last-used"

# Match the authenticator's hour-granular throttle (posthog/auth.py).
_LAST_USED_THROTTLE = timedelta(hours=1)


def _decode_last_used_marks(raw: dict[Any, Any]) -> dict[str, int]:
    """Fold an HGETALL result (bytes field -> bytes ts) into {hash: unix_ts}."""
    marks: dict[str, int] = {}
    for field, value in raw.items():
        hash_key = field.decode() if isinstance(field, bytes | bytearray) else str(field)
        raw_ts = value.decode() if isinstance(value, bytes | bytearray) else value
        try:
            marks[hash_key] = int(raw_ts)
        except (TypeError, ValueError):
            continue
    return marks


def drain_gateway_credential_last_used() -> int:
    """Stamp ProjectSecretAPIKey.last_used_at from the gateway-coalesced Valkey hash.

    phs_ only (OAuthAccessToken has no such field). bulk_update bypasses signals,
    like the authenticator's .update(), to avoid churning the cache. Returns rows updated.
    """
    if not settings.AI_GATEWAY_REDIS_URL:
        return 0

    client = get_client(settings.AI_GATEWAY_REDIS_URL)
    # Atomic read-and-clear (at-most-once): a crash before the DB commit drops
    # this window's marks. Accepted for a cosmetic, hour-granular, self-healing
    # field; process-then-delete would be at-least-once but races a gateway HSET.
    pipe = client.pipeline(transaction=True)
    pipe.hgetall(GATEWAY_CREDENTIAL_LAST_USED_KEY)
    pipe.delete(GATEWAY_CREDENTIAL_LAST_USED_KEY)
    raw = pipe.execute()[0]
    if not raw:
        return 0

    marks = _decode_last_used_marks(raw)
    if not marks:
        return 0

    to_update = []
    for secret_key in ProjectSecretAPIKey.objects.filter(secure_value__in=marks.keys()).only(
        "id", "last_used_at", "secure_value"
    ):
        ts = marks.get(secret_key.secure_value or "")
        if ts is None:
            continue
        used = datetime.fromtimestamp(ts, UTC)
        # Never regress, and honour the hour throttle against whatever last wrote it.
        if secret_key.last_used_at is None or used - secret_key.last_used_at > _LAST_USED_THROTTLE:
            secret_key.last_used_at = used
            to_update.append(secret_key)

    if to_update:
        ProjectSecretAPIKey.objects.bulk_update(to_update, ["last_used_at"])
    return len(to_update)
