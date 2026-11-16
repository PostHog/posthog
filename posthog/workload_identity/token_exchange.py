"""RFC 8693 token exchange: a workload, such as a CI job, trades its provider's OIDC token for a short-lived
project token. The incoming token is the subject token and PostHog acts as the security token service.
IETF WIMSE and SPIFFE call the caller a workload.

The workload names the project in `resource`. The exchange verifies the OIDC token against the issuer's
keys from the workload provider registry, finds the project's trust policy that matches the token's claims,
and mints a workload access token (`posthog.auth.WorkloadAccessTokenAuthentication`) that acts as the oldest
owner of the project's organization and carries the policy's whole scope ceiling. No refresh token
is issued: the workload exchanges again when it needs a new token.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import field
from enum import StrEnum
from typing import Any

from django.conf import settings
from django.utils import timezone

import jwt
import structlog
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt import PyJWK
from rest_framework import status

from posthog.api.id_jag import sign_access_token
from posthog.api.oauth.client_assertion import ClientAssertionError, JWKSUnavailableError, select_signing_key
from posthog.auth import WORKLOAD_ACCESS_TOKEN_TYPE
from posthog.dataclasses import frozen
from posthog.jwt import ASYMMETRIC_SIGNING_ALGORITHMS
from posthog.models import OrganizationMembership, Team, User
from posthog.models.workload_trust_policy import (
    WorkloadTrustPolicy,
    WorkloadTrustPolicyRequest,
    workload_trust_policy_grantable_scopes,
    workload_trust_policy_request_url,
    workload_trust_policy_version,
)
from posthog.workload_identity.providers import (
    AudienceCheck,
    WorkloadClaim,
    WorkloadProvider,
    get_supported_workload_providers,
    get_workload_provider_by_issuer,
    normalize_issuer,
)

logger = structlog.get_logger(__name__)

TOKEN_EXCHANGE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
SUBJECT_TOKEN_TYPES = frozenset({"urn:ietf:params:oauth:token-type:jwt", "urn:ietf:params:oauth:token-type:id_token"})
ISSUED_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"

WORKLOAD_ACCESS_TOKEN_MAX_LIFETIME_SECONDS = 600
WORKLOAD_TOKEN_CLOCK_SKEW_SECONDS = 30
WORKLOAD_IDENTITY_DOCS_URL = "https://posthog.com/docs/api/workload-identity"

_RESOURCE_PATH = re.compile(r"^/api/projects/(\d+)/?$")


class WorkloadExchangeErrorCode(StrEnum):
    INVALID_REQUEST = "workload_invalid_request"
    ISSUER_NOT_ALLOWED = "workload_issuer_not_allowed"
    TOKEN_INVALID = "workload_token_invalid"
    NO_MATCHING_POLICY = "workload_no_matching_policy"
    POLICY_REQUEST_PENDING = "workload_policy_request_pending"
    NO_USABLE_SCOPES = "workload_no_usable_scopes"
    NO_OWNER = "workload_no_owner"
    NOT_CONFIGURED = "workload_not_configured"
    PROVIDER_UNAVAILABLE = "workload_provider_unavailable"


class WorkloadExchangeError(Exception):
    """A refused exchange. The body follows RFC 6749 section 5.2 and adds a stable `error_code` that hog
    shows in agent mode, plus fields the error message needs, such as the approval link."""

    def __init__(
        self,
        code: WorkloadExchangeErrorCode,
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
            "error_uri": f"{WORKLOAD_IDENTITY_DOCS_URL}#{self.code.value}",
            **self.details,
        }


@frozen
class VerifiedWorkload:
    """What a verified OIDC token says about the workload, read through its provider's registry entry."""

    subject: str
    subject_name: str
    # The token's value for each condition claim the provider allows. A claim the token lacks, or holds
    # as an empty or non-scalar value, is left out, so a policy that requires it never matches.
    condition_claims: dict[str, str]
    # The claims an activity log entry records, with the same rules.
    recorded_claims: dict[str, str]

    def match_filter(self, issuer: str) -> dict[str, Any]:
        """The lookup a policy or a pending request must pass to match this workload.

        `conditions <@ token claims` holds only when each stored key is present in the token with the same
        string value, so a condition can never be skipped, and a token that lacks a condition claim matches
        nothing that sets it."""
        return {
            "issuer": issuer,
            "subject": self.subject,
            "subject_name": self.subject_name,
            "conditions__contained_by": self.condition_claims,
        }

    def claims_sent(self, provider: WorkloadProvider) -> dict[str, Any]:
        """The claims an error echoes back, so the caller can see why no policy matched."""
        return {
            "provider": provider.key,
            "subject": self.subject,
            "subject_name": self.subject_name,
            "conditions": self.condition_claims,
        }


@frozen
class IssuedWorkloadAccessToken:
    access_token: str = field(repr=False)
    scopes: list[str]
    expires_in_seconds: int
    policy_id: str


def _not_configured() -> WorkloadExchangeError:
    return WorkloadExchangeError(
        WorkloadExchangeErrorCode.NOT_CONFIGURED,
        "Workload token exchange is not configured on this server.",
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
        raise WorkloadExchangeError(
            WorkloadExchangeErrorCode.INVALID_REQUEST,
            f"Set resource to the project's API URL, for example {site_url}/api/projects/<project id>.",
            oauth_error="invalid_target",
        )
    return int(match.group(1))


def _provider_for(subject_token: str) -> WorkloadProvider:
    try:
        # The issuer picks which provider's keys verify the token, so it has to be read before the
        # signature can be checked. Nothing else from this unverified read is trusted: the verified
        # decode below checks the issuer again.
        # nosemgrep: python.jwt.security.unverified-jwt-decode.unverified-jwt-decode
        unverified = jwt.decode(subject_token, options={"verify_signature": False})
    except jwt.PyJWTError:
        raise WorkloadExchangeError(WorkloadExchangeErrorCode.TOKEN_INVALID, "subject_token is not a readable JWT.")
    issuer = str(unverified.get("iss") or "")
    provider = get_workload_provider_by_issuer(issuer)
    if provider is None:
        supported = [provider.name for provider in get_supported_workload_providers()]
        raise WorkloadExchangeError(
            WorkloadExchangeErrorCode.ISSUER_NOT_ALLOWED,
            f"PostHog doesn't trust OIDC tokens from issuer {issuer!r}. Only the supported providers are trusted.",
            details={"issuer": issuer[:255], "supported_providers": supported},
        )
    return provider


def _claim_string(value: Any) -> str | None:
    """A claim value as the string a policy compares it with, or None when it can't equal any condition.
    Policies store only non-empty strings, so an empty, null, list or object claim matches nothing. Postgres
    refuses a NUL character in text and jsonb, so a value holding one is treated as absent too."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value and "\x00" not in value:
        return value
    return None


def _claims_by_name(token_claims: dict[str, Any], wanted: tuple[WorkloadClaim, ...]) -> dict[str, str]:
    values = {claim.name: _claim_string(token_claims.get(claim.name)) for claim in wanted}
    return {name: value for name, value in values.items() if value is not None}


def _required_claim(token_claims: dict[str, Any], claim: WorkloadClaim) -> str:
    value = _claim_string(token_claims.get(claim.name))
    if value is None:
        raise WorkloadExchangeError(
            WorkloadExchangeErrorCode.TOKEN_INVALID,
            f"The OIDC token has no value for {claim.label} (claim {claim.name}).",
        )
    return value


def _signing_key(provider: WorkloadProvider, subject_token: str) -> PyJWK:
    try:
        key = select_signing_key(provider.jwks_url, subject_token)
    except JWKSUnavailableError:
        raise WorkloadExchangeError(
            WorkloadExchangeErrorCode.PROVIDER_UNAVAILABLE,
            f"Couldn't fetch {provider.name}'s signing keys. Try again in a minute.",
            oauth_error="temporarily_unavailable",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except ClientAssertionError as e:
        raise WorkloadExchangeError(
            WorkloadExchangeErrorCode.TOKEN_INVALID, f"Couldn't find the key that signed the OIDC token: {e}"
        )
    if key.algorithm_name not in ASYMMETRIC_SIGNING_ALGORITHMS or not isinstance(
        key.key, (RSAPublicKey, EllipticCurvePublicKey)
    ):
        raise WorkloadExchangeError(
            WorkloadExchangeErrorCode.TOKEN_INVALID, "The OIDC token's signing key isn't an RSA or EC key."
        )
    return key


def _expected_audience(provider: WorkloadProvider) -> str:
    match provider.audience_check:
        case AudienceCheck.SITE_URL:
            return _site_url()
        case _:
            raise _not_configured()


def _verify_subject_token(subject_token: str, provider: WorkloadProvider) -> tuple[VerifiedWorkload, int]:
    """Verify the OIDC token and return what it says about the workload and its expiry, or raise."""
    key = _signing_key(provider, subject_token)
    audience = _expected_audience(provider)
    try:
        claims = jwt.decode(
            subject_token,
            key=key,
            algorithms=[key.algorithm_name],
            audience=audience,
            leeway=WORKLOAD_TOKEN_CLOCK_SKEW_SECONDS,
            options={
                "require": ["iss", "aud", "exp", "iat", provider.subject_claim.name, provider.subject_name_claim.name]
            },
        )
    except jwt.ExpiredSignatureError:
        raise WorkloadExchangeError(WorkloadExchangeErrorCode.TOKEN_INVALID, "The OIDC token has expired.")
    except jwt.InvalidAudienceError:
        raise WorkloadExchangeError(
            WorkloadExchangeErrorCode.TOKEN_INVALID,
            f"The OIDC token's audience must be {audience}. Ask your provider for a token with that audience.",
        )
    except jwt.MissingRequiredClaimError as e:
        raise WorkloadExchangeError(WorkloadExchangeErrorCode.TOKEN_INVALID, f"The OIDC token has no {e.claim} claim.")
    except jwt.PyJWTError as e:
        logger.info("workload_token_exchange_rejected", provider=provider.key, error_type=type(e).__name__)
        raise WorkloadExchangeError(WorkloadExchangeErrorCode.TOKEN_INVALID, "The OIDC token could not be verified.")

    if normalize_issuer(str(claims.get("iss") or "")) != normalize_issuer(provider.issuer):
        raise WorkloadExchangeError(WorkloadExchangeErrorCode.TOKEN_INVALID, "The OIDC token could not be verified.")
    expires_at = claims["exp"]
    if not isinstance(expires_at, int | float):
        raise WorkloadExchangeError(
            WorkloadExchangeErrorCode.TOKEN_INVALID, "The OIDC token's exp claim must be numeric."
        )

    workload = VerifiedWorkload(
        subject=_required_claim(claims, provider.subject_claim),
        subject_name=_required_claim(claims, provider.subject_name_claim),
        condition_claims=_claims_by_name(claims, provider.condition_claims),
        recorded_claims=_claims_by_name(claims, provider.recorded_claims),
    )
    return workload, int(expires_at)


def find_matching_policy(team_id: int, issuer: str, workload: VerifiedWorkload) -> WorkloadTrustPolicy | None:
    """The project's enabled policy for this subject whose every condition equals the token's claim.

    When several match, the one with more conditions wins, then the oldest, so adding a broader policy
    never changes which policy an existing workload runs under.
    """
    candidates = WorkloadTrustPolicy.objects.for_team(team_id).filter(**workload.match_filter(issuer), enabled=True)
    matching = list(candidates)
    matching.sort(key=lambda policy: (-len(policy.conditions), policy.created_at))
    return matching[0] if matching else None


def _pending_request_for(team_id: int, issuer: str, workload: VerifiedWorkload) -> WorkloadTrustPolicyRequest | None:
    return (
        WorkloadTrustPolicyRequest.objects.for_team(team_id)
        .filter(
            **workload.match_filter(issuer),
            status=WorkloadTrustPolicyRequest.Status.PENDING,
            expires_at__gt=timezone.now(),
        )
        .order_by("-created_at")
        .first()
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
    return sign_access_token(payload, token_type=WORKLOAD_ACCESS_TOKEN_TYPE)


def exchange_workload_token(*, subject_token: str, subject_token_type: str, resource: str) -> IssuedWorkloadAccessToken:
    if not subject_token:
        raise WorkloadExchangeError(
            WorkloadExchangeErrorCode.INVALID_REQUEST, "subject_token is required.", oauth_error="invalid_request"
        )
    if subject_token_type not in SUBJECT_TOKEN_TYPES:
        raise WorkloadExchangeError(
            WorkloadExchangeErrorCode.INVALID_REQUEST,
            f"subject_token_type must be one of: {', '.join(sorted(SUBJECT_TOKEN_TYPES))}.",
            oauth_error="invalid_request",
        )
    team_id = _team_id_from_resource(resource)
    provider = _provider_for(subject_token)
    workload, oidc_expires_at = _verify_subject_token(subject_token, provider)

    team = Team.objects.select_related("organization").filter(pk=team_id).first()
    if team is not None and team.project_id != team.id:
        # Policies live on a project's own team, so an environment id never has one.
        team = None

    issuer = normalize_issuer(provider.issuer)
    # A project that doesn't exist, or an environment id, reads like a project without a matching policy,
    # so the exchange can't be used to find out which ids exist.
    policy = find_matching_policy(team.id, issuer, workload) if team is not None else None
    if team is None or policy is None:
        claims_sent = workload.claims_sent(provider)
        pending = _pending_request_for(team.id, issuer, workload) if team is not None else None
        if pending is not None:
            approval_url = workload_trust_policy_request_url(team_id, str(pending.pk))
            raise WorkloadExchangeError(
                WorkloadExchangeErrorCode.POLICY_REQUEST_PENDING,
                f"A workload trust policy for this job is waiting for an admin to approve it: {approval_url}",
                details={"approval_url": approval_url, "project_id": team_id, "claims": claims_sent},
            )
        raise WorkloadExchangeError(
            WorkloadExchangeErrorCode.NO_MATCHING_POLICY,
            f"No workload trust policy in project {team_id} matches this workload. Run `hog ci setup` to request one.",
            details={"project_id": team_id, "claims": claims_sent},
        )

    # Checked again at mint time so a scope that became ungrantable after the policy was saved is never issued.
    grantable = workload_trust_policy_grantable_scopes()
    scopes = sorted(scope for scope in policy.scopes if scope in grantable)
    if not scopes:
        raise WorkloadExchangeError(
            WorkloadExchangeErrorCode.NO_USABLE_SCOPES,
            "The matching workload trust policy grants no scopes a workload token can use. Ask an admin to edit it.",
            details={"policy_id": str(policy.pk)},
        )

    owner = oldest_owner(team.organization_id)
    if owner is None:
        raise WorkloadExchangeError(
            WorkloadExchangeErrorCode.NO_OWNER,
            "The project's organization has no active owner for workload tokens to act as.",
            http_status=status.HTTP_403_FORBIDDEN,
            oauth_error="access_denied",
        )

    now = int(time.time())
    expires_at = min(now + WORKLOAD_ACCESS_TOKEN_MAX_LIFETIME_SECONDS, oidc_expires_at)
    if expires_at <= now:
        raise WorkloadExchangeError(WorkloadExchangeErrorCode.TOKEN_INVALID, "The OIDC token has expired.")
    site_url = _site_url()
    payload: dict[str, Any] = {
        "iss": site_url,
        "aud": site_url,
        "sub": f"workload_trust_policy:{policy.pk}",
        "user_uuid": str(owner.uuid),
        "org_id": str(team.organization_id),
        "team_id": team.id,
        "policy_id": str(policy.pk),
        "policy_name": policy.name,
        "policy_version": workload_trust_policy_version(policy),
        "scope": " ".join(scopes),
        "workload": {
            "provider": provider.key,
            "subject": workload.subject,
            "subject_name": workload.subject_name,
            "claims": workload.recorded_claims,
        },
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": expires_at,
    }
    return IssuedWorkloadAccessToken(
        access_token=_sign(payload),
        scopes=scopes,
        expires_in_seconds=expires_at - now,
        policy_id=str(policy.pk),
    )
