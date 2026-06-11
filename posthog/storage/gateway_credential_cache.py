"""
Gateway credential HyperCache — purpose-built projection for the Go
ai-gateway's gateway-credential auth path (RFC #1103).

Gateway dispatch authenticates only with a phs_/pha_ gateway credential bound to
one gateway. A phc_ project token is public and cannot dispatch — it is used only
for AIO event emitting (stamping the $ai_generation envelope). This blob is
therefore credential-centric: one per phs_ project secret API key / pha_ OAuth
access token, keyed by the credential's hash so the secret never sits in a Redis
key or S3 path.

Shape:
    Key: cache/team_tokens_hashed/<sha256$hex>/team_metadata/gateway_credential.json
    Body:
        {
            "team_id": 12345,
            "project_token": "phc_...",
            "scopes": ["llm_gateway:read"],
            "gateway_slug": "posthog_code",
            "billing_mode": "internal",
            "revoked_at": null
        }

Each gateway credential is bound to exactly one gateway: the gateway's slug
is the product, equal to the $ai_gateway_slug property (the value formerly known
as $ai_product, now surfaced to non-PostHog orgs too) so internal billing stays
continuous. The Go gateway resolves key → gateway → product at auth, so the blob
carries a single gateway_slug — not a product list, and not a per-team gateway map.

The hash matches Django's hash_key_value(token, mode="sha256") = "sha256$"+hex,
which the gateway derives identically (PostHog/ai-gateway internal/auth).
team_id and project_token are load-bearing. project_token is the team's phc_ key,
carried solely so the gateway can stamp the $ai_generation event envelope (AIO
event emitting) — it never authorizes dispatch; the phs_/pha_ secret does. The
gateway fails closed if either is missing, so the projection writes a blob only
for a fully-resolvable credential and clears it otherwise. Written Redis-only (no S3): an OAuth token lives ~1h, and S3's
fixed lifecycle would outlive it, resurrecting a stale blob on a cold Redis.
"""

import os
import re
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.db import OperationalError
from django.utils import timezone

import structlog

from posthog.caching.ai_gateway_redis_cache import AI_GATEWAY_DEDICATED_CACHE_ALIAS
from posthog.models.gateway import GATEWAY_SLUG_PATTERN, Gateway
from posthog.models.oauth import OAuthAccessToken
from posthog.models.organization import OrganizationMembership
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import SHA256_HASH_PREFIX, hash_key_value
from posthog.rbac.user_access_control import UserAccessControl, ordered_access_levels
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType

logger = structlog.get_logger(__name__)

GATEWAY_CREDENTIAL_REQUIRED_SCOPE = "llm_gateway:read"

# billing_mode is provisional — the gateway treats it as opaque pass-through and
# does not enforce it yet. Open: whether it is ever non-internal.
GATEWAY_CREDENTIAL_BILLING_MODE = "internal"

# Backstop validation of gateway.slug before it lands in the blob. Gateway.save()
# already enforces this on write; re-check here because the gateway does none of
# its own and the slug flows straight onto the billing ledger.
_GATEWAY_SLUG_RE = re.compile(GATEWAY_SLUG_PATTERN)

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
    "gateway_slug",
    "billing_mode",
    "revoked_at",
]

Credential = ProjectSecretAPIKey | OAuthAccessToken


class _RefreshMemo:
    """Per-run memo for the batch refresh: the OAuth authorization checks in
    _policy_for_credential are per (org, user) and (team, user), but a refresh
    re-projects every credential — many sharing a user/team. Caching them collapses
    O(credentials) round trips into O(distinct users). Single-credential callers
    pass no memo, so their behavior is unchanged."""

    def __init__(self) -> None:
        self._memberships: dict[tuple[Any, Any], Any] = {}
        self._access: dict[tuple[Any, Any], bool] = {}

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
    """Whether the credential is literally granted llm_gateway:read.

    The literal scope only — a "*" wildcard must NOT subsume the privileged
    gateway scope (RFC #1103). The gateway rejects a blob whose scopes are "*"
    (enforced gateway-side), and the legacy "*" backward-compat wildcard is being
    retired (#60342); granting privileged gateway access off it would be an
    over-grant. A "*" client gets the scope only once it re-auths for the literal.
    """
    if isinstance(credential, ProjectSecretAPIKey):
        return GATEWAY_CREDENTIAL_REQUIRED_SCOPE in (credential.scopes or [])
    return GATEWAY_CREDENTIAL_REQUIRED_SCOPE in credential.scope.split()


def _gateway_for_credential(credential: Credential) -> Gateway | None:
    """The gateway this credential is bound to, or None if unbound.

    A secret key binds directly; an OAuth token binds through its application
    (stable across token rotation). Callers select_related the join.
    """
    if isinstance(credential, ProjectSecretAPIKey):
        return credential.gateway
    application = credential.application
    return application.gateway if application is not None else None


def _ttl_for_credential(credential: Credential) -> float:
    """Seconds the blob may live. For OAuth, the token's remaining lifetime from a
    single now() read — may be <= 0 if it expired since the policy was computed, in
    which case the caller clears instead of writing (so the expiry decision and the
    TTL share one now()). Secret keys never expire, so cap them at a short TTL the
    hourly refresh keeps warm — a missed removal self-heals instead of lasting 7 days."""
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

    # scoped_teams/scoped_organizations narrow a token below the user's full
    # membership. team_id is the gateway's canonical (project root) team, while
    # scoped_teams holds environment-level ids and the gateway attributes at the
    # project level — so a token scoped only to a non-canonical environment of this
    # project deliberately fails closed here rather than being widened project-wide.
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

    # Project access controls can revoke a member's access to this project without
    # touching org membership. check_access_level_for_object default-allows for org
    # admins, creators, and orgs without the access-control feature, so this only
    # fails closed on an explicit RBAC revocation.
    def _load_access() -> bool:
        return UserAccessControl(user=user, team=team).check_access_level_for_object(
            team, required_level=_PROJECT_READ_ACCESS_LEVEL
        )

    return memo.access(team_id, user.id, _load_access) if memo else _load_access()


def _policy_for_credential(
    credential: Credential, memo: "_RefreshMemo | None" = None
) -> dict[str, Any] | HyperCacheStoreMissing:
    """Project a credential into the wire blob, or signal a clear.

    The bound gateway is the source of truth for the billed team (not a user's
    current team), so team_id is deterministic. Fails closed on missing scope, an
    unbound credential, a team with no token, an invalid slug, or — for OAuth — an
    inactive user, expired token, out-of-scope team, or revoked membership/access.
    A project secret key is a team-owned service credential with no user, so a
    bound, slug-valid key on a team with a token is sufficient.
    """
    if not credential_has_gateway_scope(credential):
        return HyperCacheStoreMissing()

    gateway = _gateway_for_credential(credential)
    if gateway is None:
        return HyperCacheStoreMissing()

    # gateway.team is canonical (Gateway is project-scoped), so team_id matches how
    # a project token resolves. Backstop the slug — the gateway validates none of it.
    team = gateway.team
    team_id = gateway.team_id
    project_token = team.api_token
    if not project_token:
        return HyperCacheStoreMissing()

    if not _GATEWAY_SLUG_RE.match(gateway.slug):
        return HyperCacheStoreMissing()

    if isinstance(credential, OAuthAccessToken) and not _oauth_authorization_ok(credential, team, team_id, memo):
        return HyperCacheStoreMissing()

    return {
        "team_id": team_id,
        "project_token": project_token,
        "scopes": [GATEWAY_CREDENTIAL_REQUIRED_SCOPE],
        "gateway_slug": gateway.slug,
        "billing_mode": GATEWAY_CREDENTIAL_BILLING_MODE,
        "revoked_at": None,
    }


def _resolve_credential(hash_key: str) -> Credential | None:
    """Reverse a cache-key hash back to its credential (Django-side reads only;
    the gateway never calls Django). ProjectSecretAPIKey.secure_value stores the
    prefixed hash directly; OAuth.token_checksum is the bare hex, so strip the prefix."""
    secret_key = (
        ProjectSecretAPIKey.objects.select_related("team", "gateway__team").filter(secure_value=hash_key).first()
    )
    if secret_key is not None:
        return secret_key
    if hash_key.startswith(SHA256_HASH_PREFIX):
        checksum = hash_key[len(SHA256_HASH_PREFIX) :]
        return (
            OAuthAccessToken.objects.select_related("user", "application__gateway__team")
            .filter(token_checksum=checksum)
            .first()
        )
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


# Write-only from Django: project_gateway_credential / clear_gateway_credential are
# the only callers, and the Go gateway reads Redis directly. Do not call
# get_from_cache on this instance — its lazy-fill ignores _ttl_for_credential and
# would write the default cache_ttl (7 days), defeating the secret-key cap. load_fn
# exists only because HyperCache requires one.
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
    """Re-project every credential currently granted llm_gateway:read.

    Forward iteration because the cache key is a one-way hash — it can't be
    reversed through a team pool the way the team-centric refresh does. Keeps
    entries warm; signal handlers and the per-OAuth-token TTL handle removal.

    select_related pulls each credential's bound gateway and team in one query; the
    per-OAuth authorization checks (org membership, project access control) are
    memoized by (org, user) / (team, user) across the run so the refresh does
    O(distinct users) lookups, not O(credentials). Streamed via .iterator() so the
    working set stays flat. The secret-key scopes lookup uses the @> array operator,
    backed by the projectsecretapikey_scopes_gin index; the OAuth scope is a
    space-separated TextField, whitespace-bounded so the literal doesn't substring-
    match a longer scope.
    """
    now = timezone.now()
    memo = _RefreshMemo()
    querysets = (
        ProjectSecretAPIKey.objects.select_related("gateway__team").filter(
            scopes__contains=[GATEWAY_CREDENTIAL_REQUIRED_SCOPE]
        ),
        OAuthAccessToken.objects.select_related("user", "application__gateway__team").filter(
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
