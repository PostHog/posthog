from typing import Optional

from django.contrib.auth.hashers import check_password, make_password

from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from posthog.constants import AvailableFeature
from posthog.models.organization_domain import OrganizationDomain


class SCIMAuthToken:
    """
    Wrapper class to make OrganizationDomain compatible with DRF's authentication system.
    DRF expects request.user to have is_authenticated property.
    """

    def __init__(self, domain: OrganizationDomain):
        self.domain = domain
        self.is_authenticated = True
        self.is_active = True
        self.pk = None  # SCIM auth doesn't have a user PK
        self.id = None

    def __str__(self):
        return f"SCIMAuth({self.domain.domain})"


class SCIMBearerTokenAuthentication(BaseAuthentication):
    """
    SCIM authentication using bearer tokens.
    Each OrganizationDomain has its own SCIM bearer token for tenant isolation.
    """

    def authenticate(self, request: Request) -> Optional[tuple[SCIMAuthToken, OrganizationDomain]]:
        if not request.path.startswith("/scim/"):
            return None

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")

        if not auth_header.startswith("Bearer "):
            raise exceptions.AuthenticationFailed("Bearer token required for SCIM endpoints")

        token = auth_header[7:]

        if not token:
            raise exceptions.AuthenticationFailed("No bearer token provided")

        # Extract domain_id from URL path (e.g., /scim/v2/{domain_id}/Users)
        domain_id = self._extract_domain_id_from_path(request.path)
        if not domain_id:
            raise exceptions.AuthenticationFailed("Invalid SCIM URL format")

        try:
            domain = OrganizationDomain.objects.get(id=domain_id)
        except OrganizationDomain.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid organization domain")

        if not domain.has_scim:
            raise exceptions.AuthenticationFailed("SCIM not configured for this domain")

        if not domain.organization.is_feature_available(AvailableFeature.SCIM):
            raise exceptions.AuthenticationFailed("Your organization does not have the required license to use SCIM")

        # Verify the bearer token matches the stored hashed token
        if not check_password(token, domain.scim_bearer_token):
            raise exceptions.AuthenticationFailed("Invalid bearer token")

        return (SCIMAuthToken(domain), domain)

    def _extract_domain_id_from_path(self, path: str) -> Optional[str]:
        """
        Extract domain UUID from SCIM URL path.
        Expected format: /scim/v2/{domain_id}/Users or /scim/v2/{domain_id}/Groups
        """
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "scim" and parts[1] == "v2":
            return parts[2]
        return None


def generate_scim_token() -> tuple[str, str]:
    """
    Generate a new SCIM bearer token.
    Returns (plain_token, hashed_token) tuple.
    """
    import secrets

    plain_token = secrets.token_urlsafe(32)
    hashed_token = make_password(plain_token)
    return plain_token, hashed_token
