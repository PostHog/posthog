"""Verify the GitHub Actions OIDC token a pinned wizard CI workflow presents."""

import time
import threading
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.cache import cache

import jwt
import requests
import structlog

from posthog.dataclasses import frozen
from posthog.llm.wizard_gateway_token import WIZARD_GATEWAY_CONFIG_REJECTS, _parse_cap

logger = structlog.get_logger(__name__)

GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
# Fixed, so there is no operator-supplied URL to SSRF-guard.
GITHUB_OIDC_JWKS_URL = f"{GITHUB_OIDC_ISSUER}/.well-known/jwks"

_JWKS_TIMEOUT_SECONDS = 10
_JWKS_TTL_SECONDS = 300
# How long a key GitHub revoked still verifies, when refetches keep failing.
_JWKS_MAX_STALE_SECONDS = 3600
# The bound on key fetches an anonymous caller can force.
_JWKS_MIN_FETCH_INTERVAL_SECONDS = 60
_JTI_CLOCK_SKEW_SECONDS = 60
# A token valid for longer is refused: the replay marker has to outlive it.
_MAX_TOKEN_LIFETIME_SECONDS = 3600
# The claims one WIZARD_CI_IDENTITIES entry pins, in the order they are compared.
_IDENTITY_FIELDS = ("repository", "repository_id", "workflow_path", "subject")
# Optional per-entry overrides of the WIZARD_CI_* settings of the same name.
_IDENTITY_KEYS = frozenset((*_IDENTITY_FIELDS, "mints_per_hour", "mints_per_day", "program_ids", "cap_usd"))


class WizardCiOidcError(Exception):
    """The presented token is not a wizard CI identity. Never carries the token."""


class WizardCiOidcUnavailable(WizardCiOidcError):
    """A dependency needed to decide was unavailable, so the caller may retry."""


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
    # From the matched entry; None means the global setting applies.
    mints_per_hour: int | None = None
    mints_per_day: int | None = None
    program_ids: tuple[str, ...] | None = None
    cap_usd: Decimal | None = None


@frozen
class _IdentityLimits:
    mints_per_hour: int | None
    mints_per_day: int | None
    program_ids: tuple[str, ...] | None
    cap_usd: Decimal | None


_key_set: jwt.PyJWKSet | None = None
_key_set_fetched_at = 0.0
_fetch_attempted_at = 0.0
_fetch_lock = threading.Lock()


def reset_key_set_cache() -> None:
    """Test hook: drop the cached key set so the next verification refetches."""
    global _key_set, _key_set_fetched_at, _fetch_attempted_at
    _key_set, _key_set_fetched_at, _fetch_attempted_at = None, 0.0, 0.0


def _fetch_key_set() -> jwt.PyJWKSet:
    """Fetch through `requests`, which routes via the egress proxy; PyJWKClient's `urllib` does not."""
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

    A failed attempt spends the interval too, or an unreachable GitHub puts a fetch behind
    every request. The lock is non-blocking, so a caller arriving mid-fetch serves the cache.
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

    Raises WizardCiOidcUnavailable when the cache is unreachable: failing open would leave a
    captured token unbounded, and a refusal would end a run that still holds a live token.
    """
    remaining = min(claims.expires_at - int(time.time()), _MAX_TOKEN_LIFETIME_SECONDS)
    ttl = max(1, remaining + _JTI_CLOCK_SKEW_SECONDS)
    try:
        return bool(cache.add(_jti_key(claims.token_id), "1", ttl))
    except Exception as e:
        logger.warning("wizard_ci_oidc: replay cache unavailable", error=str(e))
        raise WizardCiOidcUnavailable("the CI token replay check is unavailable right now")


def release_token_id(claims: GitHubOidcClaims) -> None:
    """Give the single use back after a failure that issued no token."""
    try:
        cache.delete(_jti_key(claims.token_id))
    except Exception as e:
        logger.warning("wizard_ci_oidc: replay cache unavailable", error=str(e))


def _is_count(value: object) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 1)


def _identity_limits(entry: dict) -> _IdentityLimits | None:
    """An entry's optional limits, or None when one is present but malformed."""
    per_hour, per_day = entry.get("mints_per_hour"), entry.get("mints_per_day")
    if not _is_count(per_hour) or not _is_count(per_day):
        return None
    programs = entry.get("program_ids")
    if programs is not None and (
        not isinstance(programs, list) or not programs or not all(isinstance(p, str) and p for p in programs)
    ):
        return None
    raw_cap = entry.get("cap_usd")
    cap = None if raw_cap is None else _parse_cap(raw_cap)
    if raw_cap is not None and cap is None:
        return None
    return _IdentityLimits(
        mints_per_hour=per_hour,
        mints_per_day=per_day,
        program_ids=None if programs is None else tuple(programs),
        cap_usd=cap,
    )


def _parse_identities(entries: object) -> dict[tuple[str, ...], _IdentityLimits] | None:
    """Each entry's identity tuple with its limits, or None when any entry is malformed."""
    if not isinstance(entries, list):
        return None
    pinned: dict[tuple[str, ...], _IdentityLimits] = {}
    # Mints are counted per repository, so every entry for one must set the same counts.
    counts: dict[str, tuple[int | None, int | None]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not set(entry) <= _IDENTITY_KEYS:
            return None
        identity: tuple[Any, ...] = tuple(entry.get(field) for field in _IDENTITY_FIELDS)
        # Before the lookups below, which cannot hash a list or dict value.
        if not all(isinstance(value, str) and value for value in identity):
            return None
        limits = _identity_limits(entry)
        if limits is None or identity in pinned:
            return None
        entry_counts = (limits.mints_per_hour, limits.mints_per_day)
        if counts.setdefault(identity[0], entry_counts) != entry_counts:
            return None
        pinned[identity] = limits
    return pinned


def _pinned_identities() -> dict[tuple[str, ...], _IdentityLimits]:
    """The workflows allowed to mint, with their limits.

    A malformed list configures none, so a typo cannot leave a partial list in force.
    Counted, because CI then fails like any other refusal.
    """
    invalid = getattr(settings, "WIZARD_CI_IDENTITIES_INVALID", False)
    if settings.WIZARD_CI_IDENTITIES == [] and not invalid:
        return {}
    pinned = None if invalid else _parse_identities(settings.WIZARD_CI_IDENTITIES)
    if pinned is None:
        WIZARD_GATEWAY_CONFIG_REJECTS.labels(field="ci_identities").inc()
        return {}
    return pinned


def wizard_ci_oidc_configured() -> bool:
    """Every pin must be set: a missing one would widen the check it stands for."""
    return bool(settings.WIZARD_CI_OIDC_AUDIENCE and settings.WIZARD_CI_REPOSITORY_OWNER_ID and _pinned_identities())


def looks_like_jwt(token: str) -> bool:
    """Routes a bearer to this path. Not a security check: verify_github_oidc decides."""
    return token.count(".") == 2 and not token.startswith("ph")


def _envelope_could_match(raw: str) -> bool:
    """Whether a key lookup is worth spending; never a trust decision, since verification re-checks both."""
    try:
        claims = jwt.decode(raw, options={"verify_signature": False})
    except jwt.PyJWTError:
        return False
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    return claims.get("iss") == GITHUB_OIDC_ISSUER and settings.WIZARD_CI_OIDC_AUDIENCE in audiences


def verify_github_oidc(raw: str) -> GitHubOidcClaims:
    """Verify the signature and every workflow identity pin."""
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

    expires_at = int(claims["exp"])
    if expires_at - int(time.time()) > _MAX_TOKEN_LIFETIME_SECONDS:
        raise WizardCiOidcError("token is valid for longer than this path accepts")

    repository = str(claims.get("repository") or "")
    repository_id = str(claims.get("repository_id") or "")
    subject = str(claims.get("sub") or "")
    workflow_ref = str(claims.get("workflow_ref") or "")
    # Whole values from one entry: a reused name has a new id, `refs/heads/main` prefixes
    # `refs/heads/main-x`, and a file name may hold "@", so the path ends at the last one.
    presented = (repository, repository_id, workflow_ref.rsplit("@", 1)[0], subject)
    limits = _pinned_identities().get(presented)
    if limits is None:
        logger.warning("wizard_ci_oidc: no pinned workflow matches", repository=repository, workflow_ref=workflow_ref)
        raise WizardCiOidcError("token was issued to another workflow")

    return GitHubOidcClaims(
        repository=repository,
        repository_id=repository_id,
        repository_owner_id=owner_id,
        workflow_ref=workflow_ref,
        run_id=str(claims.get("run_id") or ""),
        token_id=str(claims["jti"]),
        expires_at=expires_at,
        mints_per_hour=limits.mints_per_hour,
        mints_per_day=limits.mints_per_day,
        program_ids=limits.program_ids,
        cap_usd=limits.cap_usd,
    )
