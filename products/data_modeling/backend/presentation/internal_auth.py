"""OIDC authentication for the data_modeling_ops internal API.

The modeling-ops admin app sits behind SSO and forwards the operator's OIDC ID token;
Django verifies it against the issuer's JWKS — signature, issuer, audience, expiry, and
the email domain. There is no shared signing secret to provision or rotate, a compromised
caller cannot mint credentials, and ``acting_user`` in the audit log is the verified email
claim rather than a self-asserted string.

Service (no-human) callers present ID tokens from the same issuer (e.g. a service
account's identity token); their emails are allow-listed via
DATA_MODELING_OPS_OIDC_SERVICE_ACCOUNT_EMAILS and exempt from the domain check.

Local dev: DATA_MODELING_OPS_OIDC_AUDIENCES defaults (DEBUG/TEST) to the gcloud CLI's
public OAuth client ID, so ``gcloud auth print-identity-token`` yields a working token
against ./bin/start with no extra setup.
"""

from functools import cache
from typing import Any

from django.conf import settings
from django.http import HttpRequest

import jwt
import structlog
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.auth import InternalAPIAuthentication, InternalAPIUser

logger = structlog.get_logger(__name__)

JWT_ALGORITHM = "RS256"


@cache
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url, cache_keys=True)


class DataModelingOpsOIDCAuthentication(InternalAPIAuthentication):
    """DRF authentication for data_modeling_ops internal API requests.

    Requires ``Authorization: Bearer <oidc-id-token>`` verified against the configured
    issuer's JWKS. Team scoping comes from the requested URL, not the token: any verified
    operator identity may call both the team-scoped and the fleet route families, which is
    the intended semantics for a read-only staff tool. Subclasses InternalAPIAuthentication
    so the router's internal-service permission short-circuit applies.
    """

    keyword = "Bearer"

    def _decode(self, token: str) -> dict[str, Any]:
        audiences = settings.DATA_MODELING_OPS_OIDC_AUDIENCES
        if not audiences:
            logger.error("data_modeling_ops_auth_not_configured")
            raise AuthenticationFailed("Internal API authentication is not configured.")

        try:
            signing_key = _jwks_client(settings.DATA_MODELING_OPS_OIDC_JWKS_URL).get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=[JWT_ALGORITHM],
                audience=audiences,
                issuer=settings.DATA_MODELING_OPS_OIDC_ISSUER,
                options={"require": ["exp", "aud", "iss"]},
            )
        except (jwt.PyJWKClientError, jwt.InvalidTokenError) as error:
            raise AuthenticationFailed("Invalid internal API token.") from error

    def _verified_identity(self, claims: dict[str, Any]) -> str:
        email = str(claims.get("email") or "").lower()
        if not email:
            raise AuthenticationFailed("Token carries no identity.")

        service_accounts = {value.lower() for value in settings.DATA_MODELING_OPS_OIDC_SERVICE_ACCOUNT_EMAILS}
        if email in service_accounts:
            return email

        if not claims.get("email_verified"):
            raise AuthenticationFailed("Token identity is not verified.")
        domain = email.rsplit("@", 1)[-1]
        if domain not in settings.DATA_MODELING_OPS_OIDC_ALLOWED_DOMAINS:
            raise AuthenticationFailed("Token identity is not allowed.")
        return email

    def authenticate(self, request: Request) -> tuple[InternalAPIUser, dict[str, Any]]:
        header = request.headers.get("Authorization", "")
        if not header.startswith(f"{self.keyword} "):
            raise AuthenticationFailed("Missing internal API token.")

        claims = self._decode(header[len(self.keyword) + 1 :].strip())
        acting_user = self._verified_identity(claims)
        user = self._get_internal_api_user(request)

        logger.info(
            "data_modeling_ops_internal_request",
            team_id=user.current_team_id,
            acting_user=acting_user,
            path=request.path,
        )
        return (user, claims)

    def authenticate_header(self, request: HttpRequest) -> str:
        return self.keyword


class DataModelingOpsAuthenticationMixin:
    """Pins a viewset to the OIDC authenticator only.

    TeamAndOrgViewSetMixin.get_authenticators always appends the session/PAT/OAuth
    authenticators after the custom ones, which on these internal routes would let any
    logged-in user through. Must precede TeamAndOrgViewSetMixin in the bases.
    """

    authentication_classes = [DataModelingOpsOIDCAuthentication]

    def get_authenticators(self) -> list[BaseAuthentication]:
        return [DataModelingOpsOIDCAuthentication()]
