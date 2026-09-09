"""Verify the GitHub Actions OIDC token the wizard CI smoke test presents.

CI holds no standing credential: the signed claims are the identity check a
user-bound mint gets from the blocklist and email verification.
"""

from typing import Any

from django.conf import settings

import jwt
import structlog

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
# Fixed and well-known, so there is no operator-supplied URL to SSRF-guard.
GITHUB_OIDC_JWKS_URL = f"{GITHUB_OIDC_ISSUER}/.well-known/jwks"

_JWKS_TIMEOUT_SECONDS = 10
# Bounds the JWK set cache only. `cache_keys` memoizes each resolved key for the
# process lifetime, so a revoked key stays accepted until restart.
_JWKS_LIFESPAN_SECONDS = 300


class WizardCiOidcError(Exception):
    """The presented token is not a wizard CI identity. Never carries the token."""


@frozen
class GitHubOidcClaims:
    """The claims the mint path is allowed to act on."""

    repository: str
    repository_owner_id: str
    workflow_ref: str
    run_id: str


_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client() -> jwt.PyJWKClient:
    """One client per process so key caching actually applies across requests."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(
            GITHUB_OIDC_JWKS_URL,
            cache_keys=True,
            lifespan=_JWKS_LIFESPAN_SECONDS,
            timeout=_JWKS_TIMEOUT_SECONDS,
        )
    return _jwks_client


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
    """Whether a key fetch is worth spending on this token.

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

    An unverifiable token refuses, a JWKS fetch that does not resolve included.
    """
    if not wizard_ci_oidc_configured():
        raise WizardCiOidcError("wizard CI OIDC is not configured on this instance")

    if not _envelope_could_match(raw):
        raise WizardCiOidcError("token failed verification")

    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(raw)
    except Exception as e:
        # PyJWKClient raises unrelated types here, so the class does not discriminate.
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
