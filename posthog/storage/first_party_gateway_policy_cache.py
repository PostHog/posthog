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
            "allowed_products": ["posthog_code", "wizard"],
            "billing_mode": "internal",
            "revoked_at": null
        }

The hash matches Django's hash_key_value(token, mode="sha256") = "sha256$"+hex,
which the gateway derives identically (PostHog/ai-gateway internal/auth/firstparty.go).
team_id and project_token are load-bearing: the gateway fails closed if either is
missing, so the projection writes a blob only for a fully-resolvable credential and
clears it otherwise. Written Redis-only (no S3): an OAuth token lives ~1h, and S3's
fixed lifecycle would outlive it, resurrecting a stale blob on a cold Redis.
"""

import os
from typing import Any

from django.conf import settings
from django.db import OperationalError
from django.utils import timezone

import structlog

from posthog.caching.ai_gateway_redis_cache import AI_GATEWAY_DEDICATED_CACHE_ALIAS
from posthog.models.oauth import OAuthAccessToken
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import SHA256_HASH_PREFIX, hash_key_value
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType

logger = structlog.get_logger(__name__)

FIRST_PARTY_REQUIRED_SCOPE = "llm_gateway:read"

# Provisional values — the gateway treats both as opaque pass-through and does
# not enforce them yet (per-product gating is an undecided follow-up, ai-gateway
# #80/#81). The authoritative allowed_products boundary is gateway-team-owned: a
# per-application_id allowlist (today services/llm-gateway products/config.py,
# moving to a DB-backed source read via this hypercache mirror — server-side
# scopes RFC #1103). Until that enforcement path is chosen, emit a stable
# placeholder rather than coupling to either design; swap these two helpers for
# the real source when it lands. Open: whether billing_mode is ever non-internal.
FIRST_PARTY_BILLING_MODE = "internal"
DEFAULT_FIRST_PARTY_PRODUCTS = ["posthog_code", "wizard"]

FIRST_PARTY_POLICY_CACHE_TTL = int(os.environ.get("FIRST_PARTY_POLICY_CACHE_TTL", str(60 * 60 * 24 * 7)))
FIRST_PARTY_POLICY_CACHE_MISS_TTL = int(os.environ.get("FIRST_PARTY_POLICY_CACHE_MISS_TTL", str(60 * 60 * 24)))

FIRST_PARTY_POLICY_FIELDS = [
    "team_id",
    "project_token",
    "scopes",
    "allowed_products",
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


def _derive_allowed_products(credential: Credential) -> list[str]:
    # Placeholder until the gateway team's per-application_id boundary is chosen
    # (see the module constants above). Not per-credential yet by design.
    return DEFAULT_FIRST_PARTY_PRODUCTS


def _ttl_for_credential(credential: Credential) -> int | None:
    """OAuth tokens expire (~1h); bound the Redis TTL so the blob can't outlive
    the token. Personal keys have no expiry, so use the default cache TTL."""
    if isinstance(credential, OAuthAccessToken) and credential.expires is not None:
        return max(0, int((credential.expires - timezone.now()).total_seconds()))
    return None


def _policy_for_credential(credential: Credential) -> dict[str, Any] | HyperCacheStoreMissing:
    """Project a credential into the wire blob, or signal a clear.

    Fails closed (returns HyperCacheStoreMissing) on anything that would make the
    gateway reject the blob: missing scope, inactive/teamless user, an expired
    OAuth token, or an unresolvable team/project_token. Never returns a partial blob.
    """
    if not credential_has_gateway_scope(credential):
        return HyperCacheStoreMissing()

    user = credential.user
    if user is None or not user.is_active:
        return HyperCacheStoreMissing()

    if isinstance(credential, OAuthAccessToken):
        if credential.application_id is None:
            return HyperCacheStoreMissing()
        if credential.expires is not None and credential.expires <= timezone.now():
            return HyperCacheStoreMissing()

    team_id = user.current_team_id
    if not team_id or team_id <= 0:
        return HyperCacheStoreMissing()

    try:
        project_token = Team.objects.values_list("api_token", flat=True).get(id=team_id)
    except Team.DoesNotExist:
        return HyperCacheStoreMissing()

    if not project_token:
        return HyperCacheStoreMissing()

    return {
        "team_id": team_id,
        "project_token": project_token,
        "scopes": [FIRST_PARTY_REQUIRED_SCOPE],
        "allowed_products": _derive_allowed_products(credential),
        "billing_mode": FIRST_PARTY_BILLING_MODE,
        "revoked_at": None,
    }


def _resolve_credential(hash_key: str) -> Credential | None:
    """Reverse a cache-key hash back to its credential (Django-side reads only;
    the gateway never calls Django). PAK.secure_value stores the prefixed hash
    directly; OAuth.token_checksum is the bare hex, so strip the prefix."""
    pak = PersonalAPIKey.objects.select_related("user").filter(secure_value=hash_key).first()
    if pak is not None:
        return pak
    if hash_key.startswith(SHA256_HASH_PREFIX):
        checksum = hash_key[len(SHA256_HASH_PREFIX) :]
        return OAuthAccessToken.objects.select_related("user", "application").filter(token_checksum=checksum).first()
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
        first_party_gateway_policy_hypercache.clear_cache(cache_hash, kinds=["redis"])
        return

    first_party_gateway_policy_hypercache.set_cache_value_redis_only(
        cache_hash, policy, ttl=_ttl_for_credential(credential)
    )


def clear_first_party_policy(credential_or_hash: Credential | str) -> None:
    cache_hash = credential_or_hash if isinstance(credential_or_hash, str) else credential_hash(credential_or_hash)
    if not cache_hash:
        return
    first_party_gateway_policy_hypercache.clear_cache(cache_hash, kinds=["redis"])


def get_first_party_policy(hash_key: str) -> dict[str, Any] | None:
    """Django-side read (lazy-fill). The gateway reads Redis/S3 directly."""
    return first_party_gateway_policy_hypercache.get_from_cache(hash_key)


def refresh_all_first_party_policies() -> int:
    """Re-project every credential currently granted llm_gateway:read.

    Forward iteration because the cache key is a one-way hash — it can't be
    reversed through a team pool the way the team-centric refresh does. Keeps
    entries warm; signal handlers and the per-OAuth-token TTL handle removal.
    """
    now = timezone.now()
    projected = 0

    for pak in (
        PersonalAPIKey.objects.select_related("user")
        .filter(scopes__contains=[FIRST_PARTY_REQUIRED_SCOPE], user__is_active=True)
        .iterator()
    ):
        project_first_party_policy(pak)
        projected += 1

    # scope is a space-separated TextField; whitespace-bounded so the literal
    # "llm_gateway:read" doesn't substring-match a longer scope. "*" is not a match.
    for token in (
        OAuthAccessToken.objects.select_related("user", "application")
        .filter(
            scope__iregex=r"(^|\s)llm_gateway:read(\s|$)",
            user__is_active=True,
            application_id__isnull=False,
            expires__gt=now,
        )
        .iterator()
    ):
        project_first_party_policy(token)
        projected += 1

    return projected
