import re
from typing import Any, Literal, TypedDict, cast

import jwt
import structlog
from jwt.algorithms import RSAAlgorithm
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.api.sso import (
    CustomGoogleOAuth2 as _CustomGoogleOAuth2,
    MultitenantSAMLAuth as _MultitenantSAMLAuth,
)
from posthog.cloud_utils import get_cached_instance_license
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.utils import ActivityCredentialMixin

from ee import settings
from ee.api.vercel.types import VercelClaims, VercelSystemClaims, VercelUser, VercelUserClaims
from ee.api.vercel.utils import get_vercel_jwks

logger = structlog.get_logger(__name__)


class MultitenantSAMLAuth(_MultitenantSAMLAuth):
    """Legacy alias for sessions created before SAML auth moved to posthog.api.sso.

    `django.contrib.auth.get_user()` only restores a session if its stored backend path is in
    `AUTHENTICATION_BACKENDS`. `authenticate()` returns None so no new session adopts this path.
    """

    name = "saml-legacy"

    def authenticate(self, request, *args, **kwargs):
        return None


class CustomGoogleOAuth2(_CustomGoogleOAuth2):
    """Legacy alias for sessions created before Google auth moved to posthog.api.sso."""

    name = "google-oauth2-legacy"

    def authenticate(self, request, *args, **kwargs):
        return None


def _get_bearer_token(request: Request) -> str | None:
    """Extract bearer token from Authorization header."""
    if auth_header := request.headers.get("authorization"):
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
    return None


class VercelAuthentication(ActivityCredentialMixin, authentication.BaseAuthentication):
    """
    Implements Vercel Marketplace API authentication.
    This authentication uses the OpenID Connect Protocol (OIDC).
    Vercel sends a JSON web token (JWT) signed with Vercel’s private key and verifiable
    using Vercel’s public JSON Web Key Sets (JWKS) available through VERCEL_JWKS_URL

    For detailed reference of User/System Auth OIDC token claims schema, see:
    https://vercel.com/docs/integrations/create-integration/marketplace-api#marketplace-partner-api-authentication
    """

    activity_credential_type = "vercel"
    VercelAuthType = Literal["user", "system"]

    VERCEL_AUTH_TYPES: tuple[VercelAuthType, ...] = ("user", "system")
    USER_SUB_RE = re.compile(r"^account:[0-9a-fA-F]+:user:[0-9a-fA-F]+$")
    SYSTEM_SUB_RE = re.compile(r"^account:[0-9a-fA-F]+$")
    VERCEL_ISSUER = "https://marketplace.vercel.com"

    def authenticate(self, request: Request) -> tuple[VercelUser, None] | None:
        token = _get_bearer_token(request)
        if not token:
            raise AuthenticationFailed("Missing Token for Vercel request")

        auth_type = self._get_vercel_auth_type(request)

        try:
            payload = self._validate_jwt_token(token, auth_type)
            self.record_activity_actor(None, str(payload.installation_id))
            return VercelUser(claims=payload), None
        except jwt.InvalidTokenError as e:
            logger.warning("Vercel auth failed", auth_type=auth_type, error=str(e), integration="vercel")
            raise AuthenticationFailed(f"Invalid {auth_type} authentication token")
        except Exception as e:
            logger.exception("Vercel auth error", auth_type=auth_type, error=str(e), integration="vercel")
            raise AuthenticationFailed(f"{auth_type.title()} authentication failed")

    def _get_vercel_auth_type(self, request: Request) -> "VercelAuthentication.VercelAuthType":
        auth_type = request.headers.get("X-Vercel-Auth", "").lower()

        if auth_type not in self.VERCEL_AUTH_TYPES:
            raise AuthenticationFailed("Missing or invalid X-Vercel-Auth header")

        return cast("VercelAuthentication.VercelAuthType", auth_type)

    def _validate_jwt_token(self, token: str, auth_type: "VercelAuthentication.VercelAuthType") -> VercelClaims:
        payload = self._decode_token(token)
        return self._validate_claims(payload, auth_type)

    def _validate_claims(
        self, payload: dict[str, Any], auth_type: "VercelAuthentication.VercelAuthType"
    ) -> VercelClaims:
        required_claims = ["iss", "sub", "aud"]

        for claim in required_claims:
            if claim not in payload:
                raise jwt.InvalidTokenError(f"Missing required claim: {claim}")

        if payload["iss"] != self.VERCEL_ISSUER:
            raise jwt.InvalidTokenError(f"Invalid issuer: {payload['iss']}")

        if auth_type == "user":
            self._validate_user_claims(payload)

            return VercelUserClaims(
                iss=payload["iss"],
                sub=payload["sub"],
                aud=payload["aud"],
                account_id=payload["account_id"],
                installation_id=payload["installation_id"],
                user_id=payload["user_id"],
                user_role=payload["user_role"],
                type=payload.get("type"),
                user_avatar_url=payload.get("user_avatar_url"),
                user_name=payload.get("user_name"),
                user_email=payload.get("user_email"),
                user_email_verified=payload.get("user_email_verified", payload.get("email_verified")),
            )
        elif auth_type == "system":
            self._validate_system_claims(payload)

            return VercelSystemClaims(
                iss=payload["iss"],
                sub=payload["sub"],
                aud=payload["aud"],
                account_id=payload["account_id"],
                installation_id=payload["installation_id"],
                type=payload.get("type"),
            )

        raise jwt.InvalidTokenError(f"Unknown auth type: {auth_type}")

    def _validate_user_claims(self, payload: dict[str, Any]) -> None:
        self._require_claims(payload, ["account_id", "installation_id", "user_id", "user_role"], "user")

        if not self.USER_SUB_RE.match(payload["sub"]):
            raise jwt.InvalidTokenError(f"Invalid User auth sub format: {payload['sub']}")

        if payload.get("user_role") not in ["ADMIN", "USER"]:
            raise jwt.InvalidTokenError(f"Invalid user_role: {payload.get('user_role')}")

    def _validate_system_claims(self, payload: dict[str, Any]) -> None:
        self._require_claims(payload, ["account_id", "installation_id"], "system")

        sub = payload.get("sub", "")
        if sub and not self.SYSTEM_SUB_RE.match(sub):
            raise jwt.InvalidTokenError(f"Invalid System auth sub format: {sub}")

    def _require_claims(self, payload: dict[str, Any], claims: list[str], auth_type: str = "") -> None:
        missing_claims = set(claims) - set(payload.keys())
        if missing_claims:
            claim_name = next(iter(missing_claims))
            msg = f"Missing required {auth_type + ' ' if auth_type else ''}claim: {claim_name}"
            raise jwt.InvalidTokenError(msg)

    def _decode_token(self, token: str) -> dict[str, Any]:
        jwks = get_vercel_jwks()
        kid = jwt.get_unverified_header(token).get("kid")
        if not kid:
            raise jwt.InvalidTokenError("Token missing key ID")

        try:
            key = RSAAlgorithm.from_jwk(next(k for k in jwks["keys"] if k.get("kid") == kid))
        except StopIteration:
            raise jwt.InvalidTokenError(f"Unable to find key with ID: {kid}")

        if not settings.VERCEL_CLIENT_INTEGRATION_ID:
            raise jwt.InvalidTokenError("VERCEL_CLIENT_INTEGRATION_ID not configured")

        return jwt.decode(
            token,
            key,  # type: ignore  # RSAAlgorithm.from_jwk returns RSAPrivateKey | RSAPublicKey, but jwt.decode accepts both
            algorithms=["RS256"],
            issuer=self.VERCEL_ISSUER,
            audience=settings.VERCEL_CLIENT_INTEGRATION_ID,
            leeway=10,  # account for clock skew with 10 seconds of leeway
        )


class BillingServiceJWTPayload(TypedDict):
    organization_id: str
    aud: str
    exp: int


class BillingServiceUser:
    """
    Represents an authenticated billing service request.
    Contains the organization_id from the validated JWT.
    """

    def __init__(self, organization_id: str):
        self.organization_id = organization_id

    @property
    def is_authenticated(self) -> bool:
        return True


class BillingServiceAuthentication(ActivityCredentialMixin, authentication.BaseAuthentication):
    """
    Authenticates requests from the billing service to PostHog.

    The billing service signs JWTs using the shared license secret (same secret PostHog
    uses when calling the billing service, but in reverse direction).
    """

    activity_credential_type = "billing_service"
    EXPECTED_AUDIENCE = "billing:posthog-proxy"

    def authenticate(self, request: Request) -> tuple[BillingServiceUser, None] | None:
        token = _get_bearer_token(request)
        if not token:
            raise AuthenticationFailed("Missing authorization token")

        try:
            payload = self._validate_jwt_token(token)
        except jwt.ExpiredSignatureError as e:
            capture_exception(e)
            logger.warning("Billing service token expired")
            raise AuthenticationFailed("Token has expired")
        except jwt.InvalidAudienceError as e:
            capture_exception(e)
            logger.warning("Billing service token has invalid audience")
            raise AuthenticationFailed("Invalid token audience")
        except jwt.InvalidTokenError as e:
            capture_exception(e)
            logger.exception("Billing service auth failed", error=str(e))
            raise AuthenticationFailed("Invalid authentication token")

        organization_id = payload.get("organization_id")
        if not organization_id:
            capture_exception(ValueError("Billing service token missing organization_id"))
            logger.warning("Billing service token missing organization_id")
            raise AuthenticationFailed("Missing organization_id in token")

        self.record_activity_actor(None)
        return BillingServiceUser(organization_id=organization_id), None

    def _validate_jwt_token(self, token: str) -> BillingServiceJWTPayload:
        license = get_cached_instance_license()
        if not license or not license.key:
            capture_exception(ValueError("Billing service auth failed: no license configured"))
            logger.error("Billing service auth failed: no license configured")
            raise AuthenticationFailed("No license configured")

        # Extract the secret from the license key (format: "id::secret")
        try:
            license_secret = license.key.split("::")[1]
        except IndexError:
            capture_exception(ValueError("Billing service auth failed: invalid license key format"))
            logger.exception("Billing service auth failed: invalid license key format")
            raise AuthenticationFailed("Invalid license key format")

        decoded_payload = jwt.decode(
            token,
            license_secret,
            algorithms=["HS256"],
            audience=self.EXPECTED_AUDIENCE,
        )

        return cast(BillingServiceJWTPayload, decoded_payload)
