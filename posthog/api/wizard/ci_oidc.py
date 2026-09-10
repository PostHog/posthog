"""Verify the GitHub Actions OIDC token the wizard CI smoke test presents.

CI holds no standing credential: the signed claims are the identity check a
user-bound mint gets from the blocklist and email verification.
"""

import time
import threading
from typing import Any

from django.conf import settings
from django.core.cache import cache

import jwt
import requests
import structlog

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
# Fixed and well-known, so there is no operator-supplied URL to SSRF-guard.
GITHUB_OIDC_JWKS_URL = f"{GITHUB_OIDC_ISSUER}/.well-known/jwks"

_JWKS_TIMEOUT_SECONDS = 10
# How long a fetched key set serves before the next verification refetches it.
_JWKS_TTL_SECONDS = 300
# How far past that a set still serves while refetches fail, and so how long a
# key GitHub revoked stays accepted.
_JWKS_MAX_STALE_SECONDS = 3600
# Bounds the outbound work an anonymous caller can force. The per-address throttle
# on the endpoint cannot: cloud trusts every proxy, so the address it reads comes
# from a header the caller writes.
_JWKS_MIN_FETCH_INTERVAL_SECONDS = 60
_JTI_CLOCK_SKEW_SECONDS = 60
# The single use is only real while the marker outlives the token, so a token
# valid for longer than this is refused rather than remembered.
_MAX_TOKEN_LIFETIME_SECONDS = 3600


class WizardCiOidcError(Exception):
    """The presented token is not a wizard CI identity. Never carries the token."""


class WizardCiOidcUnavailable(WizardCiOidcError):
    """No signing key was available to decide. Retryable, unlike a refusal."""


@frozen
class GitHubOidcClaims:
    """The claims the mint path is allowed to act on."""

    repository: str
    repository_id: str
    repository_owner_id: str
    workflow_ref: str
    run_id: str
    token_id: str
    expires_at: int


_key_set: jwt.PyJWKSet | None = None
_key_set_fetched_at = 0.0
_fetch_attempted_at = 0.0
_fetch_lock = threading.Lock()


def reset_key_set_cache() -> None:
    """Test hook: drop the cached key set so the next verification refetches."""
    global _key_set, _key_set_fetched_at, _fetch_attempted_at
    _key_set, _key_set_fetched_at, _fetch_attempted_at = None, 0.0, 0.0


def _fetch_key_set() -> jwt.PyJWKSet:
    """Fetch through `requests`, which is what routes the call via the egress proxy.

    PyJWKClient reaches for `urllib`, which does not.
    """
    response = requests.get(GITHUB_OIDC_JWKS_URL, timeout=_JWKS_TIMEOUT_SECONDS, allow_redirects=False)
    response.raise_for_status()
    return jwt.PyJWKSet.from_dict(response.json())


def _match_kid(key_set: jwt.PyJWKSet, kid: str) -> Any | None:
    for key in key_set.keys:
        if key.key_id == kid and key.public_key_use in ("sig", None):
            return key
    return None


def _servable(now: float) -> jwt.PyJWKSet | None:
    if _key_set is None or now - _key_set_fetched_at >= _JWKS_MAX_STALE_SECONDS:
        return None
    return _key_set


def _current_key_set(kid: str) -> jwt.PyJWKSet | None:
    """The key set to verify against, refetching at most once per interval.

    A failed attempt spends the interval too, or an unreachable GitHub puts a
    fresh outbound request behind every inbound one. The lock is taken without
    blocking, so a caller arriving mid-fetch serves what is cached rather than
    parking a worker on a 10 second call.
    """
    global _key_set, _key_set_fetched_at, _fetch_attempted_at
    now = time.monotonic()
    cached = _servable(now)
    if cached is not None and now - _key_set_fetched_at < _JWKS_TTL_SECONDS and _match_kid(cached, kid) is not None:
        return cached
    if not _fetch_lock.acquire(blocking=False):
        return cached
    try:
        now = time.monotonic()
        if _fetch_attempted_at and now - _fetch_attempted_at < _JWKS_MIN_FETCH_INTERVAL_SECONDS:
            return _servable(now)
        _fetch_attempted_at = now
        try:
            _key_set = _fetch_key_set()
            _key_set_fetched_at = now
        except Exception as e:
            logger.warning("wizard_ci_oidc: key set fetch failed", error=str(e))
        return _servable(time.monotonic())
    finally:
        _fetch_lock.release()


def _signing_key(kid: str) -> Any:
    key_set = _current_key_set(kid)
    if key_set is None:
        raise WizardCiOidcUnavailable("no GitHub signing key is available right now")
    key = _match_kid(key_set, kid)
    if key is None:
        raise WizardCiOidcError("token was signed by an unrecognized key")
    return key


def _jti_key(token_id: str) -> str:
    return f"wizard_ci_oidc:jti:{token_id}"


def consume_token_id(claims: GitHubOidcClaims) -> bool:
    """Whether this token is being presented for the first time.

    False when the cache is unreachable. The hourly mint limit lives in the same
    cache, so failing open here would leave a captured token bounded by nothing
    at all; a CI run that fails while Redis is down is the cheaper outcome.
    """
    remaining = min(claims.expires_at - int(time.time()), _MAX_TOKEN_LIFETIME_SECONDS)
    ttl = max(1, remaining + _JTI_CLOCK_SKEW_SECONDS)
    try:
        return bool(cache.add(_jti_key(claims.token_id), "1", ttl))
    except Exception as e:
        logger.warning("wizard_ci_oidc: replay cache unavailable", error=str(e))
        return False


def release_token_id(claims: GitHubOidcClaims) -> None:
    """Give the single use back after a failure that issued no token."""
    try:
        cache.delete(_jti_key(claims.token_id))
    except Exception as e:
        logger.warning("wizard_ci_oidc: replay cache unavailable", error=str(e))


def wizard_ci_oidc_configured() -> bool:
    """Every pin must be set: a missing one would widen the check it stands for."""
    return bool(
        settings.WIZARD_CI_OIDC_AUDIENCE
        and settings.WIZARD_CI_REPOSITORY
        and settings.WIZARD_CI_REPOSITORY_ID
        and settings.WIZARD_CI_REPOSITORY_OWNER_ID
        and settings.WIZARD_CI_WORKFLOW_PATH
        and settings.WIZARD_CI_SUBJECT
    )


def looks_like_jwt(token: str) -> bool:
    """Routes a bearer to this path. Not a security check: verify_github_oidc decides."""
    return token.count(".") == 2 and not token.startswith("ph")


def _envelope_could_match(raw: str) -> bool:
    """Whether a key lookup is worth spending on this token.

    Never a trust decision: verify_github_oidc re-checks both against the signed
    payload.
    """
    try:
        claims = jwt.decode(raw, options={"verify_signature": False})
    except jwt.PyJWTError:
        return False
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    return claims.get("iss") == GITHUB_OIDC_ISSUER and settings.WIZARD_CI_OIDC_AUDIENCE in audiences


def verify_github_oidc(raw: str) -> GitHubOidcClaims:
    """Verify the signature and every workflow identity pin.

    An unverifiable token refuses, a key set that does not resolve included.
    """
    if not wizard_ci_oidc_configured():
        raise WizardCiOidcError("wizard CI OIDC is not configured on this instance")

    if not _envelope_could_match(raw):
        raise WizardCiOidcError("token failed verification")

    try:
        kid = jwt.get_unverified_header(raw).get("kid")
    except jwt.PyJWTError:
        raise WizardCiOidcError("token failed verification")
    if not kid:
        raise WizardCiOidcError("token failed verification")

    signing_key = _signing_key(kid)

    try:
        claims: dict[str, Any] = jwt.decode(
            raw,
            signing_key.key,
            algorithms=["RS256"],
            issuer=GITHUB_OIDC_ISSUER,
            audience=settings.WIZARD_CI_OIDC_AUDIENCE,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "jti"]},
        )
    except jwt.PyJWTError as e:
        logger.warning("wizard_ci_oidc: token rejected", error=str(e))
        raise WizardCiOidcError("token failed verification")

    owner_id = str(claims.get("repository_owner_id") or "")
    if owner_id != str(settings.WIZARD_CI_REPOSITORY_OWNER_ID):
        raise WizardCiOidcError("token was issued to another repository owner")

    repository = str(claims.get("repository") or "")
    if repository != settings.WIZARD_CI_REPOSITORY:
        raise WizardCiOidcError("token was issued to another repository")

    # Bounded so the replay marker can cover the whole life of what it admits.
    expires_at = int(claims["exp"])
    if expires_at - int(time.time()) > _MAX_TOKEN_LIFETIME_SECONDS:
        raise WizardCiOidcError("token is valid for longer than this path accepts")

    # A rename frees both names for anyone to claim. The numeric ids never move.
    repository_id = str(claims.get("repository_id") or "")
    if repository_id != str(settings.WIZARD_CI_REPOSITORY_ID):
        raise WizardCiOidcError("token was issued to another repository")

    # `sub` carries the trigger and the ref, so it pins which branch ran. Compared
    # whole because `refs/heads/main` is a prefix of `refs/heads/main-x`.
    subject = str(claims.get("sub") or "")
    if subject != settings.WIZARD_CI_SUBJECT:
        raise WizardCiOidcError("token was issued to another workflow")

    # workflow_ref is "<owner>/<repo>/<path>@<ref>"; a prefix stopping at the "@"
    # would leave every ref matching.
    workflow_ref = str(claims.get("workflow_ref") or "")
    if workflow_ref.split("@", 1)[0] != settings.WIZARD_CI_WORKFLOW_PATH:
        raise WizardCiOidcError("token was issued to another workflow")

    return GitHubOidcClaims(
        repository=repository,
        repository_id=repository_id,
        repository_owner_id=owner_id,
        workflow_ref=workflow_ref,
        run_id=str(claims.get("run_id") or ""),
        token_id=str(claims["jti"]),
        expires_at=expires_at,
    )
