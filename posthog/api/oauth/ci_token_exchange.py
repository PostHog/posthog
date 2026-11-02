"""RFC 8693 token exchange: a CI job trades its provider's OIDC token for a short-lived project token.

The job names the project in `resource`. The exchange verifies the OIDC token against the issuer's
keys from the CI provider registry, finds the project's trust policy that matches the token's claims,
and mints a CI access token (`posthog.auth.CIAccessTokenAuthentication`) that acts as the oldest
owner of the project's organization and carries the policy's whole scope ceiling. No refresh token
is issued: the job exchanges again when it needs a new token.
"""

from __future__ import annotations

import re
import time
import uuid
import dataclasses
from dataclasses import field
from enum import StrEnum
from typing import Any

from django.conf import settings

import jwt
import structlog
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt import PyJWK
from rest_framework import status

from posthog.api.id_jag import sign_access_token
from posthog.api.oauth.ci_providers import (
    AudienceCheck,
    CIProvider,
    get_ci_provider_by_issuer,
    get_supported_ci_providers,
    normalize_issuer,
)
from posthog.api.oauth.client_assertion import ClientAssertionError, select_signing_key
from posthog.auth import CI_ACCESS_TOKEN_TYPE
from posthog.dataclasses import frozen
from posthog.jwt import ASYMMETRIC_SIGNING_ALGORITHMS
from posthog.models import OrganizationMembership, Team, User
from posthog.models.ci_trust_policy import (
    CITrustPolicy,
    CITrustPolicyRequest,
    ci_trust_policy_grantable_scopes,
    ci_trust_policy_request_url,
    ci_trust_policy_version,
)

logger = structlog.get_logger(__name__)

TOKEN_EXCHANGE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
SUBJECT_TOKEN_TYPES = frozenset({"urn:ietf:params:oauth:token-type:jwt", "urn:ietf:params:oauth:token-type:id_token"})
ISSUED_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"

CI_ACCESS_TOKEN_MAX_LIFETIME_SECONDS = 600
CI_OIDC_CLOCK_SKEW_SECONDS = 30
CI_OIDC_DOCS_URL = "https://posthog.com/docs/api/ci-oidc"

_RESOURCE_PATH = re.compile(r"^/api/projects/(\d+)/?$")


class CIExchangeErrorCode(StrEnum):
    INVALID_REQUEST = "ci_invalid_request"
    ISSUER_NOT_ALLOWED = "ci_issuer_not_allowed"
    TOKEN_INVALID = "ci_token_invalid"
    NO_MATCHING_POLICY = "ci_no_matching_policy"
    POLICY_REQUEST_PENDING = "ci_policy_request_pending"
    NO_USABLE_SCOPES = "ci_no_usable_scopes"
    NO_OWNER = "ci_no_owner"
    NOT_CONFIGURED = "ci_not_configured"


class CIExchangeError(Exception):
    """A refused exchange. The body follows RFC 6749 section 5.2 and adds a stable `error_code` that hog
    shows in agent mode, plus fields the error message needs, such as the approval link."""

    def __init__(
        self,
        code: CIExchangeErrorCode,
        description: str,
        *,
        oauth_error: str = "invalid_grant",
        http_status: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(description)
        self.code = code
        self.description = description
        self.oauth_error = oauth_error
        self.http_status = http_status
        self.details = details or {}

    def body(self) -> dict[str, Any]:
        return {
            "error": self.oauth_error,
            "error_description": self.description,
            "error_code": self.code.value,
            "error_uri": f"{CI_OIDC_DOCS_URL}#{self.code.value}",
            **self.details,
        }


@frozen
class CIClaims:
    repository: str
    repository_id: str
    ref: str
    environment: str
    workflow: str
    run_id: str
    sha: str


@frozen
class IssuedCIAccessToken:
    access_token: str = field(repr=False)
    scopes: list[str]
    expires_in_seconds: int
    policy_id: str


def _not_configured() -> CIExchangeError:
    return CIExchangeError(
        CIExchangeErrorCode.NOT_CONFIGURED,
        "CI token exchange is not configured on this server.",
        oauth_error="server_error",
        http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _site_url() -> str:
    site_url = (settings.SITE_URL or "").rstrip("/")
    if not site_url:
        raise _not_configured()
    return site_url


def _team_id_from_resource(resource: str) -> int:
    site_url = _site_url()
    resource = resource.strip()
    match = _RESOURCE_PATH.match(resource[len(site_url) :]) if resource.startswith(f"{site_url}/") else None
    if match is None:
        raise CIExchangeError(
            CIExchangeErrorCode.INVALID_REQUEST,
            f"Set resource to the project's API URL, for example {site_url}/api/projects/<project id>.",
            oauth_error="invalid_target",
        )
    return int(match.group(1))


def _provider_for(subject_token: str) -> CIProvider:
    try:
        # The issuer picks which provider's keys verify the token, so it has to be read before the
        # signature can be checked. Nothing else from this unverified read is trusted: the verified
        # decode below checks the issuer again.
        # nosemgrep: python.jwt.security.unverified-jwt-decode.unverified-jwt-decode
        unverified = jwt.decode(subject_token, options={"verify_signature": False})
    except jwt.PyJWTError:
        raise CIExchangeError(CIExchangeErrorCode.TOKEN_INVALID, "subject_token is not a readable JWT.")
    issuer = str(unverified.get("iss") or "")
    provider = get_ci_provider_by_issuer(issuer)
    if provider is None:
        supported = [provider.name for provider in get_supported_ci_providers()]
        raise CIExchangeError(
            CIExchangeErrorCode.ISSUER_NOT_ALLOWED,
            f"PostHog doesn't trust OIDC tokens from issuer {issuer!r}. Only the listed CI providers are trusted.",
            details={"issuer": issuer[:255], "supported_providers": supported},
        )
    return provider


def _claim(claims: dict[str, Any], name: str | None) -> str:
    if name is None:
        return ""
    value = claims.get(name)
    return "" if value is None else str(value)


def _signing_key(provider: CIProvider, subject_token: str) -> PyJWK:
    try:
        key = select_signing_key(provider.jwks_url, subject_token)
    except ClientAssertionError as e:
        raise CIExchangeError(
            CIExchangeErrorCode.TOKEN_INVALID, f"Couldn't find the key that signed the OIDC token: {e}"
        )
    if key.algorithm_name not in ASYMMETRIC_SIGNING_ALGORITHMS or not isinstance(
        key.key, (RSAPublicKey, EllipticCurvePublicKey)
    ):
        raise CIExchangeError(CIExchangeErrorCode.TOKEN_INVALID, "The OIDC token's signing key isn't an RSA or EC key.")
    return key


def _expected_audience(provider: CIProvider) -> str:
    match provider.audience_check:
        case AudienceCheck.SITE_URL:
            return _site_url()
        case _:
            raise _not_configured()


def _verify_subject_token(subject_token: str, provider: CIProvider) -> tuple[CIClaims, int]:
    """Verify the OIDC token and return its claims and expiry, or raise."""
    key = _signing_key(provider, subject_token)
    audience = _expected_audience(provider)
    mapping = provider.claims
    try:
        claims = jwt.decode(
            subject_token,
            key=key,
            algorithms=[key.algorithm_name],
            audience=audience,
            leeway=CI_OIDC_CLOCK_SKEW_SECONDS,
            options={"require": ["iss", "aud", "exp", "iat", mapping.repository, mapping.repository_id]},
        )
    except jwt.ExpiredSignatureError:
        raise CIExchangeError(CIExchangeErrorCode.TOKEN_INVALID, "The OIDC token has expired.")
    except jwt.InvalidAudienceError:
        raise CIExchangeError(
            CIExchangeErrorCode.TOKEN_INVALID,
            f"The OIDC token's audience must be {audience}. Ask your CI provider for a token with that audience.",
        )
    except jwt.MissingRequiredClaimError as e:
        raise CIExchangeError(CIExchangeErrorCode.TOKEN_INVALID, f"The OIDC token has no {e.claim} claim.")
    except jwt.PyJWTError as e:
        logger.info("ci_token_exchange_rejected", provider=provider.key, error_type=type(e).__name__)
        raise CIExchangeError(CIExchangeErrorCode.TOKEN_INVALID, "The OIDC token could not be verified.")

    if normalize_issuer(str(claims.get("iss") or "")) != normalize_issuer(provider.issuer):
        raise CIExchangeError(CIExchangeErrorCode.TOKEN_INVALID, "The OIDC token could not be verified.")
    expires_at = claims["exp"]
    if not isinstance(expires_at, int | float):
        raise CIExchangeError(CIExchangeErrorCode.TOKEN_INVALID, "The OIDC token's exp claim must be numeric.")

    ci_claims = CIClaims(
        repository=_claim(claims, mapping.repository),
        repository_id=_claim(claims, mapping.repository_id),
        ref=_claim(claims, mapping.ref),
        environment=_claim(claims, mapping.environment),
        workflow=_claim(claims, mapping.workflow),
        run_id=_claim(claims, mapping.run_id),
        sha=_claim(claims, mapping.sha),
    )
    if not ci_claims.repository or not ci_claims.repository_id:
        raise CIExchangeError(CIExchangeErrorCode.TOKEN_INVALID, "The OIDC token doesn't name a repository.")
    return ci_claims, int(expires_at)


def _conditions_match(candidate: CITrustPolicy | CITrustPolicyRequest, ci_claims: CIClaims) -> bool:
    return (not candidate.ref or candidate.ref == ci_claims.ref) and (
        not candidate.environment or candidate.environment == ci_claims.environment
    )


def find_matching_policy(team_id: int, issuer: str, ci_claims: CIClaims) -> CITrustPolicy | None:
    """The project's enabled policy for this repository whose ref and environment conditions hold.

    When several match, the one with more conditions wins, then the oldest, so adding a broader policy
    never changes which policy an existing job runs under.
    """
    candidates = CITrustPolicy.objects.for_team(team_id).filter(
        issuer=issuer,
        repository_id=ci_claims.repository_id,
        repository=ci_claims.repository,
        enabled=True,
    )
    matching = [policy for policy in candidates if _conditions_match(policy, ci_claims)]
    matching.sort(key=lambda policy: (-(bool(policy.ref) + bool(policy.environment)), policy.created_at))
    return matching[0] if matching else None


def _pending_request_for(team_id: int, issuer: str, ci_claims: CIClaims) -> CITrustPolicyRequest | None:
    requests = (
        CITrustPolicyRequest.objects.for_team(team_id)
        .filter(
            issuer=issuer,
            repository_id=ci_claims.repository_id,
            repository=ci_claims.repository,
            status=CITrustPolicyRequest.Status.PENDING,
        )
        .order_by("-created_at")
    )
    return next(
        (
            request
            for request in requests
            if request.effective_status == CITrustPolicyRequest.Status.PENDING and _conditions_match(request, ci_claims)
        ),
        None,
    )


def oldest_owner(organization_id: Any) -> User | None:
    membership = (
        OrganizationMembership.objects.filter(
            organization_id=organization_id,
            level=OrganizationMembership.Level.OWNER,
            user__is_active=True,
        )
        .select_related("user")
        .order_by("joined_at", "id")
        .first()
    )
    return membership.user if membership else None


def _sign(payload: dict[str, Any]) -> str:
    if not getattr(settings, "OIDC_RSA_PRIVATE_KEY", None):
        raise _not_configured()
    return sign_access_token(payload, token_type=CI_ACCESS_TOKEN_TYPE)


def exchange_ci_token(*, subject_token: str, subject_token_type: str, resource: str) -> IssuedCIAccessToken:
    if not subject_token:
        raise CIExchangeError(
            CIExchangeErrorCode.INVALID_REQUEST, "subject_token is required.", oauth_error="invalid_request"
        )
    if subject_token_type not in SUBJECT_TOKEN_TYPES:
        raise CIExchangeError(
            CIExchangeErrorCode.INVALID_REQUEST,
            f"subject_token_type must be one of: {', '.join(sorted(SUBJECT_TOKEN_TYPES))}.",
            oauth_error="invalid_request",
        )
    team_id = _team_id_from_resource(resource)
    provider = _provider_for(subject_token)
    ci_claims, oidc_expires_at = _verify_subject_token(subject_token, provider)

    team = Team.objects.select_related("organization").filter(pk=team_id).first()
    if team is not None and team.project_id != team.id:
        raise CIExchangeError(
            CIExchangeErrorCode.INVALID_REQUEST,
            "Set resource to the project's API URL. An environment of a project can't be named on its own.",
            oauth_error="invalid_target",
        )

    issuer = normalize_issuer(provider.issuer)
    # A project that doesn't exist reads like one without a matching policy, so the exchange can't be
    # used to find out which project ids exist.
    policy = find_matching_policy(team.id, issuer, ci_claims) if team is not None else None
    if team is None or policy is None:
        claims_sent = {
            field: getattr(ci_claims, field) for field in ("repository", "repository_id", "ref", "environment")
        }
        pending = _pending_request_for(team.id, issuer, ci_claims) if team is not None else None
        if pending is not None:
            approval_url = ci_trust_policy_request_url(team_id, str(pending.pk))
            raise CIExchangeError(
                CIExchangeErrorCode.POLICY_REQUEST_PENDING,
                f"A CI trust policy for this job is waiting for an admin to approve it: {approval_url}",
                details={"approval_url": approval_url, "project_id": team_id, "claims": claims_sent},
            )
        raise CIExchangeError(
            CIExchangeErrorCode.NO_MATCHING_POLICY,
            f"No CI trust policy in project {team_id} matches this job. Run `hog ci setup` to request one.",
            details={"project_id": team_id, "claims": claims_sent},
        )

    # Checked again at mint time so a scope that became ungrantable after the policy was saved is never issued.
    grantable = ci_trust_policy_grantable_scopes()
    scopes = sorted(scope for scope in policy.scopes if scope in grantable)
    if not scopes:
        raise CIExchangeError(
            CIExchangeErrorCode.NO_USABLE_SCOPES,
            "The matching CI trust policy grants no scopes a CI token can use. Ask an admin to edit it.",
            details={"policy_id": str(policy.pk)},
        )

    owner = oldest_owner(team.organization_id)
    if owner is None:
        raise CIExchangeError(
            CIExchangeErrorCode.NO_OWNER,
            "The project's organization has no active owner for CI tokens to act as.",
            http_status=status.HTTP_403_FORBIDDEN,
            oauth_error="access_denied",
        )

    now = int(time.time())
    expires_at = min(now + CI_ACCESS_TOKEN_MAX_LIFETIME_SECONDS, oidc_expires_at)
    if expires_at <= now:
        raise CIExchangeError(CIExchangeErrorCode.TOKEN_INVALID, "The OIDC token has expired.")
    site_url = _site_url()
    payload: dict[str, Any] = {
        "iss": site_url,
        "aud": site_url,
        "sub": f"ci_trust_policy:{policy.pk}",
        "user_uuid": str(owner.uuid),
        "org_id": str(team.organization_id),
        "team_id": team.id,
        "policy_id": str(policy.pk),
        "policy_name": policy.name,
        "policy_version": ci_trust_policy_version(policy),
        "scope": " ".join(scopes),
        "ci": {"provider": provider.key, **dataclasses.asdict(ci_claims)},
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": expires_at,
    }
    return IssuedCIAccessToken(
        access_token=_sign(payload),
        scopes=scopes,
        expires_in_seconds=expires_at - now,
        policy_id=str(policy.pk),
    )
