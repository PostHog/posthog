"""Verify the GitHub Actions OIDC token the wizard CI smoke test presents.

CI holds no standing credential: the signed claims are the identity check a
user-bound mint gets from the blocklist and email verification.
"""

import time
import threading
from typing import Any

from django.conf import settings

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
# Also how long a key GitHub has revoked stays accepted.
_JWKS_TTL_SECONDS = 300
# Floor between refetches forced by an unrecognised `kid`, which bounds outbound
# requests to GitHub no matter how many source addresses ask.
_JWKS_FORCED_REFRESH_INTERVAL_SECONDS = 60


class WizardCiOidcError(Exception):
    """The presented token is not a wizard CI identity. Never carries the token."""


@frozen
class GitHubOidcClaims:
    """The claims the mint path is allowed to act on."""

    repository: str
    repository_owner_id: str
    workflow_ref: str
    run_id: str


_key_set: jwt.PyJWKSet | None = None
_key_set_fetched_at = 0.0
_forced_refresh_at = 0.0
_refresh_lock = threading.Lock()


def reset_key_set_cache() -> None:
    """Test hook: drop the cached key set so the next verification refetches."""
    global _key_set, _key_set_fetched_at, _forced_refresh_at
    _key_set, _key_set_fetched_at, _forced_refresh_at = None, 0.0, 0.0


def _fetch_key_set() -> jwt.PyJWKSet:
    """Fetch through `requests` so the call follows the egress proxy Django runs behind.

    PyJWKClient reaches for `urllib` instead, which is not how anything else here
    leaves the cluster.
    """
    response = requests.get(GITHUB_OIDC_JWKS_URL, timeout=_JWKS_TIMEOUT_SECONDS, allow_redirects=False)
    response.raise_for_status()
    return jwt.PyJWKSet.from_dict(response.json())


def _cached_key_set(force: bool) -> jwt.PyJWKSet:
    global _key_set, _key_set_fetched_at
    now = time.monotonic()
    if not force and _key_set is not None and now - _key_set_fetched_at < _JWKS_TTL_SECONDS:
        return _key_set
    fetched = _fetch_key_set()
    _key_set, _key_set_fetched_at = fetched, now
    return fetched


def _match_kid(key_set: jwt.PyJWKSet, kid: str) -> Any | None:
    for key in key_set.keys:
        if key.key_id == kid and key.public_key_use in ("sig", None):
            return key
    return None


def _claim_forced_refresh() -> bool:
    """Whether this caller may refetch now. One caller wins per interval."""
    global _forced_refresh_at
    now = time.monotonic()
    with _refresh_lock:
        if _forced_refresh_at and now - _forced_refresh_at < _JWKS_FORCED_REFRESH_INTERVAL_SECONDS:
            return False
        _forced_refresh_at = now
        return True


def _signing_key(kid: str) -> Any:
    """Resolve `kid`, refetching for an unrecognised one at most once per interval.

    PyJWKClient refetches the whole set on every miss, which would let an anonymous
    caller drive one request to GitHub per token it invents.
    """
    key = _match_kid(_cached_key_set(force=False), kid)
    if key is not None:
        return key
    if not _claim_forced_refresh():
        raise WizardCiOidcError("could not resolve the signing key for this token")
    key = _match_kid(_cached_key_set(force=True), kid)
    if key is None:
        raise WizardCiOidcError("could not resolve the signing key for this token")
    return key


def wizard_ci_oidc_configured() -> bool:
    """Every pin must be set: a missing one would widen the check it stands for."""
    return bool(
        settings.WIZARD_CI_OIDC_AUDIENCE
        and settings.WIZARD_CI_REPOSITORY
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

    try:
        signing_key = _signing_key(kid)
    except WizardCiOidcError:
        raise
    except Exception as e:
        logger.warning("wizard_ci_oidc: signing key unavailable", error=str(e))
        raise WizardCiOidcError("could not resolve the signing key for this token")

    try:
        claims: dict[str, Any] = jwt.decode(
            raw,
            signing_key.key,
            algorithms=["RS256"],
            issuer=GITHUB_OIDC_ISSUER,
            audience=settings.WIZARD_CI_OIDC_AUDIENCE,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as e:
        logger.warning("wizard_ci_oidc: token rejected", error=str(e))
        raise WizardCiOidcError("token failed verification")

    # An org rename frees the name for anyone to claim; the numeric id never moves.
    owner_id = str(claims.get("repository_owner_id") or "")
    if owner_id != str(settings.WIZARD_CI_REPOSITORY_OWNER_ID):
        raise WizardCiOidcError("token was issued to another repository owner")

    repository = str(claims.get("repository") or "")
    if repository != settings.WIZARD_CI_REPOSITORY:
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
        repository_owner_id=owner_id,
        workflow_ref=workflow_ref,
        run_id=str(claims.get("run_id") or ""),
    )
