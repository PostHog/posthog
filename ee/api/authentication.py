from typing import Any, Union, Optional
from functools import lru_cache
import re
import jwt
from jwt.algorithms import RSAAlgorithm
import requests
from requests.models import Response

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http.response import HttpResponse
from django.urls.base import reverse
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied, AuthenticationFailed
from rest_framework import authentication
from rest_framework.request import Request
from django.contrib.auth.models import AnonymousUser
from social_core.backends.saml import (
    OID_COMMON_NAME,
    OID_GIVEN_NAME,
    OID_MAIL,
    OID_SURNAME,
    OID_USERID,
    SAMLAuth,
    SAMLIdentityProvider,
)
from social_core.backends.google import GoogleOAuth2
from social_core.exceptions import AuthFailed, AuthMissingParameter
from social_django.utils import load_backend, load_strategy

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain
from social_django.models import UserSocialAuth


VERCEL_JWKS_URL = "https://marketplace.vercel.com/.well-known/jwks.json"
VERCEL_ISSUER = "https://marketplace.vercel.com"


@lru_cache(maxsize=1)
def get_vercel_jwks() -> dict[str, Any]:
    response: Response = requests.get(VERCEL_JWKS_URL, timeout=10)
    response.raise_for_status()
    return response.json()


class VercelAuthentication(authentication.BaseAuthentication):
    """
    Implements Vercel Marketplace API authentication.
    https://vercel.com/docs/integrations/create-integration/marketplace-api#marketplace-partner-api-authentication
    """

    def authenticate_header(self, request: Request) -> str:
        return 'Bearer realm="vercel-integration"'

    def authenticate(self, request: Request) -> Optional[tuple[AnonymousUser, dict[str, Any]]]:
        """Authentication logic that uses X-Vercel-Auth header to determine validation type"""
        token = self._get_bearer_token(request)
        if not token:
            return None

        auth_type = self._get_vercel_auth_type(request)

        try:
            payload = self._validate_jwt_token(token, auth_type)
            return AnonymousUser(), payload
        except jwt.InvalidTokenError as e:
            raise AuthenticationFailed(f"Invalid {auth_type} JWT token: {str(e)}")
        except Exception as e:
            raise AuthenticationFailed(f"{auth_type} authentication failed: {str(e)}")

    def _get_vercel_auth_type(self, request: Request) -> str:
        """Extract auth type from X-Vercel-Auth header"""
        auth_type = request.headers.get("X-Vercel-Auth", "").lower()
        if auth_type in ["system", "user"]:
            return auth_type.title()
        raise AuthenticationFailed("Missing or invalid X-Vercel-Auth header")

    def _validate_jwt_token(self, token: str, auth_type: str) -> dict[str, Any]:
        """Validate JWT token using Vercel's JWKS"""
        # Get the token header to find the key ID
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        if not kid:
            raise jwt.InvalidTokenError("Token missing key ID")

        # Get JWKS and find the matching key
        jwks = get_vercel_jwks()
        public_key = self._get_public_key_from_jwks(jwks, kid)

        # Verify and decode the token
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=VERCEL_ISSUER,
            options={"verify_aud": False},  # TODO: Skip audience verification for now
        )

        # Validate claims based on auth type
        self._validate_claims(payload, auth_type)

        return payload

    def _get_public_key_from_jwks(self, jwks: dict[str, Any], kid: str):
        """Extract the public key for the given key ID from JWKS"""
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return RSAAlgorithm.from_jwk(key)

        raise jwt.InvalidTokenError(f"Unable to find key with ID: {kid}")

    def _validate_claims(self, payload: dict[str, Any], auth_type: str) -> None:
        """Validate Vercel JWT claims based on auth type"""
        # Base required claims
        required_claims = ["iss", "sub", "aud"]

        for claim in required_claims:
            if claim not in payload:
                raise jwt.InvalidTokenError(f"Missing required claim: {claim}")

        if payload["iss"] != VERCEL_ISSUER:
            raise jwt.InvalidTokenError(f"Invalid issuer: {payload['iss']}")

        # Validate claims specific to auth type
        if auth_type == "User":
            self._validate_user_claims(payload)
        elif auth_type == "System":
            self._validate_system_claims(payload)
        else:
            raise jwt.InvalidTokenError(f"Unsupported auth type: {auth_type}")

    def _validate_user_claims(self, payload: dict[str, Any]) -> None:
        user_required_claims = ["account_id", "installation_id", "user_id", "user_role"]

        for claim in user_required_claims:
            if claim not in payload:
                raise jwt.InvalidTokenError(f"Missing required User auth claim: {claim}")

        # Validate sub format for user (matches /^account:[0-9a-fA-F]+:user:[0-9a-fA-F]+$/)
        sub = payload.get("sub", "")
        if not re.match(r"^account:[0-9a-fA-F]+:user:[0-9a-fA-F]+$", sub):
            raise jwt.InvalidTokenError(f"Invalid User auth sub format: {sub}")

        # Validate user_role
        if payload.get("user_role") not in ["ADMIN", "USER"]:
            raise jwt.InvalidTokenError(f"Invalid user_role: {payload.get('user_role')}")

    def _validate_system_claims(self, payload: dict[str, Any]) -> None:
        system_required_claims = ["account_id", "installation_id"]

        for claim in system_required_claims:
            if claim not in payload:
                raise jwt.InvalidTokenError(f"Missing required System auth claim: {claim}")

        # Validate sub format for system (matches /^account:[0-9a-fA-F]+$/)
        sub = payload.get("sub", "")
        if sub and not re.match(r"^account:[0-9a-fA-F]+$", sub):
            raise jwt.InvalidTokenError(f"Invalid System auth sub format: {sub}")

        # installation_id can be null for system auth - just validate it exists
        if "installation_id" not in payload:
            raise jwt.InvalidTokenError("Missing installation_id claim")

    def _get_bearer_token(self, request: Request) -> Optional[str]:
        auth_header = request.META.get("HTTP_AUTHORIZATION")

        if auth_header:
            parts = auth_header.split(" ")
            if len(parts) == 2 and parts[0].lower() == "bearer":
                return parts[1]

        return None


@api_view(["GET"])
def saml_metadata_view(request, *args, **kwargs):
    if (
        not request.user.organization_memberships.get(organization=request.user.organization).level
        >= OrganizationMembership.Level.ADMIN
    ):
        raise PermissionDenied("You need to be an administrator or owner to access this resource.")

    complete_url = reverse("social:complete", args=("saml",))
    saml_backend = load_backend(load_strategy(request), "saml", redirect_uri=complete_url)
    metadata, errors = saml_backend.generate_metadata_xml()

    if not errors:
        return HttpResponse(content=metadata, content_type="text/xml")


class MultitenantSAMLAuth(SAMLAuth):
    """
    Implements our own version of SAML auth that supports multitenancy. Instead of relying on instance-based config via env vars,
    each organization can have multiple verified domains each with its own SAML configuration.
    """

    def get_idp(self, organization_domain_or_id: Union["OrganizationDomain", str]):
        try:
            organization_domain = (
                organization_domain_or_id
                if isinstance(organization_domain_or_id, OrganizationDomain)
                else OrganizationDomain.objects.verified_domains().get(id=organization_domain_or_id)
            )
        except (OrganizationDomain.DoesNotExist, DjangoValidationError):
            raise AuthFailed("saml", "Authentication request is invalid. Invalid RelayState.")

        if not organization_domain.organization.is_feature_available(AvailableFeature.SAML):
            raise AuthFailed(
                "saml",
                "Your organization does not have the required license to use SAML.",
            )

        return SAMLIdentityProvider(
            str(organization_domain.id),
            entity_id=organization_domain.saml_entity_id,
            url=organization_domain.saml_acs_url,
            x509cert=organization_domain.saml_x509_cert,
        )

    def auth_url(self):
        """
        Overridden to use the config from the relevant OrganizationDomain
        Get the URL to which we must redirect in order to
        authenticate the user
        """
        email = self.strategy.request_data().get("email")

        if not email:
            raise AuthMissingParameter("saml", "email")

        instance = OrganizationDomain.objects.get_verified_for_email_address(email=email)

        if not instance or not instance.has_saml:
            raise AuthFailed("saml", "SAML not configured for this user.")

        auth = self._create_saml_auth(idp=self.get_idp(instance))
        # Below, return_to sets the RelayState, which contains the ID of
        # the `OrganizationDomain`.  We use it to store the specific SAML IdP
        # name, since we multiple IdPs share the same auth_complete URL.
        return auth.login(return_to=str(instance.id))

    def _get_attr(
        self,
        response_attributes: dict[str, Any],
        attribute_names: list[str],
        optional: bool = False,
    ) -> str:
        """
        Fetches a specific attribute from the SAML response, attempting with multiple different attribute names.
        We attempt multiple attribute names to make it easier for admins to configure SAML (less configuration to set).
        """
        output = None
        for _attr in attribute_names:
            if _attr in response_attributes:
                output = response_attributes[_attr]
                break

        if not output and not optional:
            raise AuthMissingParameter("saml", attribute_names[0])

        if isinstance(output, list):
            output = output[0]

        return output

    def get_user_details(self, response):
        """
        Overridden to find attributes across multiple possible names.
        """
        attributes = response["attributes"]
        return {
            "fullname": self._get_attr(
                attributes,
                ["full_name", "FULL_NAME", "fullName", OID_COMMON_NAME],
                optional=True,
            ),
            "first_name": self._get_attr(
                attributes,
                [
                    "first_name",
                    "FIRST_NAME",
                    "firstName",
                    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname",
                    OID_GIVEN_NAME,
                ],
                optional=True,
            ),
            "last_name": self._get_attr(
                attributes,
                [
                    "last_name",
                    "LAST_NAME",
                    "lastName",
                    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname",
                    OID_SURNAME,
                ],
                optional=True,
            ),
            "email": self._get_attr(
                attributes,
                [
                    "email",
                    "EMAIL",
                    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
                    OID_MAIL,
                ],
            ),
        }

    def get_user_id(self, details, response):
        """
        Overridden to find user ID across multiple attribute names.
        Get the permanent ID for this user from the response.
        """
        USER_ID_ATTRIBUTES = ["name_id", "NAME_ID", "nameId", OID_USERID]
        uid = self._get_attr(response["attributes"], USER_ID_ATTRIBUTES)
        return f"{response['idp_name']}:{uid}"


class CustomGoogleOAuth2(GoogleOAuth2):
    def auth_extra_arguments(self):
        extra_args = super().auth_extra_arguments()
        email = self.strategy.request.GET.get("email")

        if email:
            extra_args["login_hint"] = email

        return extra_args

    def get_user_id(self, details, response):
        """
        Retrieve and migrate Google OAuth user identification.

        Note: While social-auth-core supports using Google's sub claim via
        settings.USE_UNIQUE_USER_ID = True, this setting was not enabled historically
        in our application. This led to emails being stored as uids instead of the
        more stable Google sub identifier.

        'sub' (subject identifier) is part of OpenID Connect and is guaranteed to be a
        stable, unique identifier for the user within Google's system. It's designed
        specifically for authentication purposes and won't change even if the user changes
        their email or other profile details.

        This method handles two types of user identification:
        1. Legacy users: Originally stored with email as their uid (due to missing USE_UNIQUE_USER_ID)
        2. New users: Using Google's sub claim (unique identifier) as uid

        The method first checks if a user exists with the sub as uid. If not found,
        it looks for a legacy user with email as uid and migrates them to use sub.
        This ensures a smooth transition from email-based to sub-based identification
        while maintaining backward compatibility.

        Args:
            details: User details dictionary from OAuth response
            response: Full OAuth response from Google

        Returns:
            str: The Google sub claim to be used as uid
        """
        email = response.get("email")
        sub = response.get("sub")

        if not sub:
            raise ValueError("Google OAuth response missing 'sub' claim")

        try:
            # First try: Find user by sub (preferred method)
            social_auth = UserSocialAuth.objects.get(provider="google-oauth2", uid=sub)
            return sub
        except UserSocialAuth.DoesNotExist:
            pass

        try:
            # Second try: Find and migrate legacy user using email as uid
            social_auth = UserSocialAuth.objects.get(provider="google-oauth2", uid=email)
            # Migrate user from email to sub
            social_auth.uid = sub
            social_auth.save()
            return sub
        except UserSocialAuth.DoesNotExist:
            # No existing user found - use sub for new account
            return sub
