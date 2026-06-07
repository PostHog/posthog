"""
Gateway credential HyperCache — purpose-built projection for the Go
ai-gateway's gateway-credential auth path (RFC #1103).

Where the team-centric llm_gateway_policy.json blob admits a whole team by its
phc_ project token, this one is credential-centric: one blob per phx_ personal
API key / pha_ OAuth access token, keyed by the credential's hash so the secret
never sits in a Redis key or S3 path.

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
team_id and project_token are load-bearing: the gateway fails closed if either is
missing, so the projection writes a blob only for a fully-resolvable credential and
clears it otherwise. Written Redis-only (no S3): an OAuth token lives ~1h, and S3's
fixed lifecycle would outlive it, resurrecting a stale blob on a cold Redis.
"""

import os
import re
from typing import Any

from django.conf import settings
from django.db import OperationalError
from django.utils import timezone

import structlog

from posthog.caching.ai_gateway_redis_cache import AI_GATEWAY_DEDICATED_CACHE_ALIAS
from posthog.constants import AvailableFeature
from posthog.models.gateway import GATEWAY_SLUG_PATTERN, Gateway
from posthog.models.oauth import OAuthAccessToken
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
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

# Caps the PAK blob TTL so a signal-bypassing removal (e.g. .update()) self-heals
# in hours, not the 7-day default. Must stay above the hourly refresh interval.
GATEWAY_CREDENTIAL_PAK_CACHE_TTL = int(os.environ.get("GATEWAY_CREDENTIAL_PAK_CACHE_TTL", str(60 * 60 * 6)))

GATEWAY_CREDENTIAL_FIELDS = [
    "team_id",
    "project_token",
    "scopes",
    "gateway_slug",
    "billing_mode",
    "revoked_at",
]

Credential = PersonalAPIKey | OAuthAccessToken


def credential_hash(credential: Credential) -> str | None:
    """The sha256$<hex> cache-key hash for a credential.

    PersonalAPIKey.secure_value already stores hash_key_value(token); OAuth keeps
    the plaintext token, so hash it the same way (its token_checksum is bare hex,
    which would not match the gateway's sha256$-prefixed derivation).
    """
    if isinstance(credential, PersonalAPIKey):
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
    if isinstance(credential, PersonalAPIKey):
        return GATEWAY_CREDENTIAL_REQUIRED_SCOPE in (credential.scopes or [])
    return GATEWAY_CREDENTIAL_REQUIRED_SCOPE in credential.scope.split()


def _gateway_for_credential(credential: Credential) -> Gateway | None:
    """The gateway this credential is bound to, or None if unbound.

    A personal key binds directly; an OAuth token binds through its application
    (stable across token rotation). Callers select_related the join.
    """
    if isinstance(credential, PersonalAPIKey):
        return credential.gateway
    application = credential.application
    return application.gateway if application is not None else None


def _ttl_for_credential(credential: Credential) -> float:
    """Seconds the blob may live. For OAuth, the token's remaining lifetime from a
    single now() read — may be <= 0 if it expired since the policy was computed, in
    which case the caller clears instead of writing (so the expiry decision and the
    TTL share one now()). Personal keys never expire, so cap them at a short TTL the
    hourly refresh keeps warm — a missed removal self-heals instead of lasting 7 days."""
    if isinstance(credential, OAuthAccessToken):
        return (credential.expires - timezone.now()).total_seconds()
    return GATEWAY_CREDENTIAL_PAK_CACHE_TTL


def _policy_for_credential(credential: Credential) -> dict[str, Any] | HyperCacheStoreMissing:
    """Project a credential into the wire blob, or signal a clear.

    The bound gateway is the source of truth for the billed team (not the user's
    current team), so team_id is deterministic. Fails closed on missing scope,
    inactive user, expired token, unbound credential, a team with no token, or a
    user who is no longer a member of the billed team's org.
    """
    if not credential_has_gateway_scope(credential):
        return HyperCacheStoreMissing()

    user = credential.user
    if user is None or not user.is_active:
        return HyperCacheStoreMissing()

    if isinstance(credential, OAuthAccessToken):
        if credential.application_id is None:
            return HyperCacheStoreMissing()
        if credential.expires <= timezone.now():
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

    # scoped_teams/scoped_organizations narrow a credential below the user's full
    # membership. The gateway can't see them, so the projection is the only
    # enforcement point — fail closed if the bound gateway's team is out of scope.
    #
    # team_id is the gateway's canonical (project root) team. scoped_teams holds
    # environment-level team ids, and the gateway authenticates/attributes at the
    # project level — it cannot honor a per-environment narrowing. So a credential
    # scoped only to a non-canonical environment of this project deliberately fails
    # closed here rather than being silently widened to project-wide access. (A
    # loud rejection at credential-bind time is the better long-term home for this,
    # once that API exists.)
    if credential.scoped_teams and team_id not in credential.scoped_teams:
        return HyperCacheStoreMissing()
    if credential.scoped_organizations and str(team.organization_id) not in credential.scoped_organizations:
        return HyperCacheStoreMissing()

    # The gateway authenticates from the cached blob alone, so every authorization
    # input it can't see is enforced here (and re-checked by the hourly refresh).
    # scoped_organizations is a static ceiling that doesn't track these changing.
    membership = (
        OrganizationMembership.objects.select_related("organization")
        .filter(organization_id=team.organization_id, user_id=user.id)
        .first()
    )
    if membership is None:
        return HyperCacheStoreMissing()

    # Org security setting can forbid non-admin members from using personal API
    # keys; OAuth tokens are exempt, mirroring PersonalAPIKeyAuthentication.
    if isinstance(credential, PersonalAPIKey):
        org = membership.organization
        if (
            org.is_feature_available(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS)
            and not org.members_can_use_personal_api_keys
            and membership.level < OrganizationMembership.Level.ADMIN
        ):
            return HyperCacheStoreMissing()

    # Project access controls can revoke a member's access to this project without
    # touching org membership. check_access_level_for_object default-allows for org
    # admins, creators, and orgs without the access-control feature, so this only
    # fails closed on an explicit RBAC revocation.
    user_access_control = UserAccessControl(user=user, team=team)
    if not user_access_control.check_access_level_for_object(team, required_level=_PROJECT_READ_ACCESS_LEVEL):
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
    the gateway never calls Django). PAK.secure_value stores the prefixed hash
    directly; OAuth.token_checksum is the bare hex, so strip the prefix."""
    pak = PersonalAPIKey.objects.select_related("user", "gateway__team").filter(secure_value=hash_key).first()
    if pak is not None:
        return pak
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
# would write the default cache_ttl (7 days), defeating the PAK cap. load_fn exists
# only because HyperCache requires one.
gateway_credential_hypercache = HyperCache(
    namespace="team_metadata",
    value="gateway_credential.json",
    hashed_credential_based=True,
    load_fn=_load_gateway_credential,
    cache_ttl=GATEWAY_CREDENTIAL_CACHE_TTL,
    cache_miss_ttl=GATEWAY_CREDENTIAL_CACHE_MISS_TTL,
    cache_alias=(AI_GATEWAY_DEDICATED_CACHE_ALIAS if AI_GATEWAY_DEDICATED_CACHE_ALIAS in settings.CACHES else None),
)


def project_gateway_credential(credential: Credential) -> None:
    """Write (or clear) the credential's policy blob from current DB state."""
    cache_hash = credential_hash(credential)
    if not cache_hash:
        return

    policy = _policy_for_credential(credential)
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

    select_related pulls each credential's bound gateway and team in one query, but
    the authorization checks in _policy_for_credential (org membership, personal-key
    restriction, project access control) each issue their own query — intentionally
    O(n) in the credential count, bounded because llm_gateway:read is admin-granted.
    The org personal-key setting change propagates through this hourly pass plus the
    PAK TTL rather than a per-input signal (access-control changes have their own
    reproject signal). Streamed via .iterator() so the
    working set stays flat. scope is a space-separated TextField; whitespace-bounded
    so the literal doesn't substring-match a longer scope.
    """
    now = timezone.now()
    querysets = (
        PersonalAPIKey.objects.select_related("user", "gateway__team").filter(
            scopes__contains=[GATEWAY_CREDENTIAL_REQUIRED_SCOPE], user__is_active=True
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
            project_gateway_credential(credential)
            count += 1

    return count
