"""
First-party gateway policy HyperCache — purpose-built projection for the Go
ai-gateway's first-party auth path (RFC #1103).

Where the team-centric llm_gateway_policy.json blob admits a whole team by its
phc_ project token, this one is credential-centric: one blob per phx_ personal
API key / pha_ OAuth access token, keyed by the credential's hash so the secret
never sits in a Redis key or S3 path.

Shape:
    Key: cache/team_tokens_hashed/<sha256$hex>/team_metadata/first_party_policy.json
    Body:
        {
            "team_id": 12345,
            "project_token": "phc_...",
            "scopes": ["llm_gateway:read"],
            "gateway_slug": "posthog_code",
            "billing_mode": "internal",
            "revoked_at": null
        }

Each first-party credential is bound to exactly one gateway: the gateway's slug
is the product, equal to the $ai_gateway_slug property (the value formerly known
as $ai_product, now surfaced to non-PostHog orgs too) so internal billing stays
continuous. The Go gateway resolves key → gateway → product at auth, so the blob
carries a single gateway_slug — not a product list, and not a per-team gateway map.

The hash matches Django's hash_key_value(token, mode="sha256") = "sha256$"+hex,
which the gateway derives identically (PostHog/ai-gateway internal/auth/firstparty.go).
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
from posthog.models.gateway import GATEWAY_SLUG_PATTERN, Gateway
from posthog.models.oauth import OAuthAccessToken
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import SHA256_HASH_PREFIX, hash_key_value
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType

logger = structlog.get_logger(__name__)

FIRST_PARTY_REQUIRED_SCOPE = "llm_gateway:read"

# billing_mode is provisional — the gateway treats it as opaque pass-through and
# does not enforce it yet. Open: whether it is ever non-internal.
FIRST_PARTY_BILLING_MODE = "internal"

# Backstop validation of gateway.slug before it lands in the blob. Gateway.save()
# already enforces this on write; re-check here because the gateway does none of
# its own and the slug flows straight onto the billing ledger.
_GATEWAY_SLUG_RE = re.compile(GATEWAY_SLUG_PATTERN)

FIRST_PARTY_POLICY_CACHE_TTL = int(os.environ.get("FIRST_PARTY_POLICY_CACHE_TTL", str(60 * 60 * 24 * 7)))
FIRST_PARTY_POLICY_CACHE_MISS_TTL = int(os.environ.get("FIRST_PARTY_POLICY_CACHE_MISS_TTL", str(60 * 60 * 24)))

# Caps the PAK blob TTL so a signal-bypassing removal (e.g. .update()) self-heals
# in hours, not the 7-day default. Must stay above the hourly refresh interval.
FIRST_PARTY_POLICY_PAK_CACHE_TTL = int(os.environ.get("FIRST_PARTY_POLICY_PAK_CACHE_TTL", str(60 * 60 * 6)))

FIRST_PARTY_POLICY_FIELDS = [
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
    (firstparty_test.go), and the legacy "*" backward-compat wildcard is being
    retired (#60342); granting privileged gateway access off it would be an
    over-grant. A "*" client gets the scope only once it re-auths for the literal.
    """
    if isinstance(credential, PersonalAPIKey):
        return FIRST_PARTY_REQUIRED_SCOPE in (credential.scopes or [])
    return FIRST_PARTY_REQUIRED_SCOPE in credential.scope.split()


def _gateway_for_credential(credential: Credential) -> Gateway | None:
    """The gateway this credential is bound to, or None if unbound.

    A personal key binds directly; an OAuth token binds through its application
    (stable across token rotation). Callers select_related the join.
    """
    if isinstance(credential, PersonalAPIKey):
        return credential.gateway
    application = credential.application
    return application.gateway if application is not None else None


def _ttl_for_credential(credential: Credential) -> int | None:
    """OAuth tokens expire (~1h); bound the Redis TTL so the blob can't outlive
    the token. Personal keys never expire, so cap them at a short TTL the hourly
    refresh keeps warm — a missed removal self-heals instead of lasting 7 days.

    expires is non-nullable on OAuthAccessToken. max(1, …) floors the TTL at one
    second so a token with sub-second remaining isn't written with timeout=0,
    which Django treats as evict-immediately."""
    if isinstance(credential, OAuthAccessToken):
        return max(1, int((credential.expires - timezone.now()).total_seconds()))
    return FIRST_PARTY_POLICY_PAK_CACHE_TTL


def _policy_for_credential(credential: Credential) -> dict[str, Any] | HyperCacheStoreMissing:
    """Project a credential into the wire blob, or signal a clear.

    The bound gateway is the source of truth for the billed team (not the user's
    current team), so team_id is deterministic. Fails closed on missing scope,
    inactive user, expired token, unbound credential, or a team with no token.
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
    if credential.scoped_teams and team_id not in credential.scoped_teams:
        return HyperCacheStoreMissing()
    if credential.scoped_organizations and str(team.organization_id) not in credential.scoped_organizations:
        return HyperCacheStoreMissing()

    return {
        "team_id": team_id,
        "project_token": project_token,
        "scopes": [FIRST_PARTY_REQUIRED_SCOPE],
        "gateway_slug": gateway.slug,
        "billing_mode": FIRST_PARTY_BILLING_MODE,
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


def _load_first_party_policy(hash_key: KeyType) -> dict[str, Any] | HyperCacheStoreMissing:
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
        logger.exception("Database error loading first-party gateway policy", error_type=type(e).__name__)
        return HyperCacheStoreMissing()


first_party_gateway_policy_hypercache = HyperCache(
    namespace="team_metadata",
    value="first_party_policy.json",
    hashed_credential_based=True,
    load_fn=_load_first_party_policy,
    cache_ttl=FIRST_PARTY_POLICY_CACHE_TTL,
    cache_miss_ttl=FIRST_PARTY_POLICY_CACHE_MISS_TTL,
    cache_alias=(AI_GATEWAY_DEDICATED_CACHE_ALIAS if AI_GATEWAY_DEDICATED_CACHE_ALIAS in settings.CACHES else None),
)


def project_first_party_policy(credential: Credential) -> None:
    """Write (or clear) the credential's policy blob from current DB state."""
    cache_hash = credential_hash(credential)
    if not cache_hash:
        return

    policy = _policy_for_credential(credential)
    if isinstance(policy, HyperCacheStoreMissing):
        first_party_gateway_policy_hypercache.delete_cache_entry(cache_hash, kinds=["redis"])
        return

    first_party_gateway_policy_hypercache.set_cache_value_redis_only(
        cache_hash, policy, ttl=_ttl_for_credential(credential)
    )


def clear_first_party_policy(credential_or_hash: Credential | str) -> None:
    cache_hash = credential_or_hash if isinstance(credential_or_hash, str) else credential_hash(credential_or_hash)
    if not cache_hash:
        return
    first_party_gateway_policy_hypercache.delete_cache_entry(cache_hash, kinds=["redis"])


def get_first_party_policy(hash_key: str) -> dict[str, Any] | None:
    """Django-side read (lazy-fill). The gateway reads Redis/S3 directly."""
    return first_party_gateway_policy_hypercache.get_from_cache(hash_key)


def refresh_all_first_party_policies() -> int:
    """Re-project every credential currently granted llm_gateway:read.

    Forward iteration because the cache key is a one-way hash — it can't be
    reversed through a team pool the way the team-centric refresh does. Keeps
    entries warm; signal handlers and the per-OAuth-token TTL handle removal.

    select_related pulls each credential's bound gateway and its team in the same
    query, so there's no N+1 lookup. Streamed via .iterator() so the working set
    stays flat as the number of gateway-scoped credentials grows. scope is a
    space-separated TextField; whitespace-bounded so the literal doesn't
    substring-match a longer scope.
    """
    now = timezone.now()
    querysets = (
        PersonalAPIKey.objects.select_related("user", "gateway__team").filter(
            scopes__contains=[FIRST_PARTY_REQUIRED_SCOPE], user__is_active=True
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
            project_first_party_policy(credential)
            count += 1

    return count
