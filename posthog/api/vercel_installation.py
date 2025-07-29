"""
Implements the Vercel Marketplace API server for managing marketplace installations.

See:
https://vercel.com/docs/integrations/create-integration/marketplace-api
"""

from functools import lru_cache
from typing import Any, Optional
import re
import jwt
from jwt.algorithms import RSAAlgorithm

import requests
from django.contrib.auth.models import AnonymousUser
from rest_framework import serializers, viewsets, permissions, authentication, exceptions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import mixins
from posthog.models.vercel_installation import VercelInstallation

VERCEL_JWKS_URL = "https://marketplace.vercel.com/.well-known/jwks.json"
VERCEL_ISSUER = "https://marketplace.vercel.com"


@lru_cache(maxsize=1)
def get_vercel_jwks() -> dict[str, Any]:
    """Fetch JWKS from Vercel with basic in-memory caching"""
    response = requests.get(VERCEL_JWKS_URL, timeout=10)
    response.raise_for_status()
    return response.json()


class VercelAuthentication(authentication.BaseAuthentication):
    """
    Unified Vercel JWT authentication that determines auth type from X-Vercel-Auth header.
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
            raise exceptions.AuthenticationFailed(f"Invalid {auth_type} JWT token: {str(e)}")
        except Exception as e:
            raise exceptions.AuthenticationFailed(f"{auth_type} authentication failed: {str(e)}")

    def _get_vercel_auth_type(self, request: Request) -> str:
        """Extract auth type from X-Vercel-Auth header"""
        auth_type = request.headers.get("X-Vercel-Auth", "").lower()
        if auth_type in ["system", "user"]:
            return auth_type.title()
        raise exceptions.AuthenticationFailed("Missing or invalid X-Vercel-Auth header")

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
        """Validate User Auth specific claims"""
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
        """Validate System Auth specific claims"""
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


class VercelInstallationPermission(permissions.BasePermission):
    """
    Custom permission that validates Vercel auth type and installation ID match.
    """

    SUPPORTED_AUTH_TYPES = {
        "destroy": ["User"],
        "retrieve": ["User", "System"],
        "update": ["User", "System"],
        "partial_update": ["User", "System"],
    }

    def has_permission(self, request: Request, view) -> bool:
        self._validate_auth_type_allowed(request, view)
        return True

    def has_object_permission(self, request: Request, view, obj) -> bool:
        self._validate_installation_id_match(request, view)
        return True

    def _get_supported_auth_types(self, view) -> list[str]:
        """Get supported auth types for the current action"""
        return self.SUPPORTED_AUTH_TYPES.get(view.action, ["User", "System"])

    def _validate_auth_type_allowed(self, request: Request, view) -> None:
        """Validate that the auth type from X-Vercel-Auth header is allowed for this endpoint"""
        auth_type = request.headers.get("X-Vercel-Auth", "").lower()
        if not auth_type:
            raise exceptions.AuthenticationFailed("Missing X-Vercel-Auth header")

        auth_type_title = auth_type.title()
        supported_types = self._get_supported_auth_types(view)

        if auth_type_title not in supported_types:
            raise exceptions.PermissionDenied(
                f"Auth type '{auth_type_title}' not allowed for this endpoint. "
                f"Supported types: {', '.join(supported_types)}"
            )

    def _validate_installation_id_match(self, request: Request, view) -> None:
        """Validate that JWT installation_id matches URL parameter"""
        jwt_payload = self._get_jwt_payload(request)
        installation_id = view.kwargs.get("installation_id")

        if jwt_payload.get("installation_id") != installation_id:
            raise exceptions.PermissionDenied("Installation ID mismatch")

    def _get_jwt_payload(self, request: Request) -> dict[str, Any]:
        """Extract JWT payload from authenticated request"""
        if hasattr(request, "auth") and isinstance(request.auth, dict) and request.auth:
            return request.auth
        raise exceptions.AuthenticationFailed("No valid JWT authentication found")


class VercelCredentialsSerializer(serializers.Serializer):
    access_token = serializers.CharField(help_text="Access token authorizes marketplace and integration APIs.")
    token_type = serializers.CharField(help_text="The type of token (default: Bearer).")


class VercelContactSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="Contact email address for the account.")
    name = serializers.CharField(required=False, allow_blank=True, help_text="Contact name for the account (optional).")


class VercelAccountSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True, help_text="Account name (optional).")
    url = serializers.URLField(help_text="URL of the account.")
    contact = VercelContactSerializer(help_text="Contact information for the account.")


class UpsertInstallationPayloadSerializer(serializers.Serializer):
    scopes = serializers.ListField(
        child=serializers.CharField(), min_length=1, help_text="Array of scopes, must have at least one. Min Length: 1"
    )
    acceptedPolicies = serializers.DictField(
        child=serializers.JSONField(),
        help_text='Policies accepted by the customer. Example: { "toc": "2024-02-28T10:00:00Z" }',
    )
    credentials = VercelCredentialsSerializer(
        help_text="The service-account access token to access marketplace and integration APIs on behalf of a customer's installation."
    )
    account = VercelAccountSerializer(
        help_text="The account information for this installation. Use Get Account Info API to re-fetch this data post installation."
    )


class VercelInstallationSerializer(serializers.ModelSerializer):
    class Meta:
        model = VercelInstallation
        fields = "__all__"


class VercelInstallationViewSet(
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    queryset = VercelInstallation.objects.all()
    serializer_class = VercelInstallationSerializer
    lookup_field = "installation_id"
    authentication_classes = [VercelAuthentication]
    permission_classes = [VercelInstallationPermission]

    def _validate_upsert_payload(self, request: Request) -> None:
        """Validate the upsert installation payload"""
        serializer = UpsertInstallationPayloadSerializer(data=request.data)
        if not serializer.is_valid():
            raise exceptions.ValidationError(detail=serializer.errors)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self._validate_upsert_payload(request)
        return super().update(request, *args, **kwargs)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().retrieve(request, *args, **kwargs)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self._validate_upsert_payload(request)
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().destroy(request, *args, **kwargs)
