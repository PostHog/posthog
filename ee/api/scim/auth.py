import secrets
from dataclasses import dataclass, field
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
        self.id = domain.idp_config.scim_slug

    def __str__(self):
        return f"SCIMAuth({self.domain.domain})"


class SCIMBearerTokenAuthentication(BaseAuthentication):
    """
    SCIM authentication using bearer tokens.
    Each linked IdentityProviderConfig has its own SCIM bearer token for tenant isolation.
    """

    def authenticate(self, request: Request) -> Optional[tuple[SCIMAuthToken, OrganizationDomain]]:
        if not request.path.startswith("/scim/"):
            return None

        auth_header = request.headers.get("authorization", "")
        token = auth_header[7:] if auth_header.startswith("Bearer ") else ""

        if not token:
            raise exceptions.NotAuthenticated("Bearer token required for SCIM endpoints")

        # Extract the config slug from the URL path (e.g., /scim/v2/{scim_slug}/Users)
        scim_slug = self._extract_scim_slug_from_path(request.path)
        if not scim_slug:
            raise exceptions.AuthenticationFailed("Invalid SCIM URL format")

        try:
            # nosemgrep: idor-lookup-without-org (SCIM bearer token auth, config slug is tenant identifier)
            domain = OrganizationDomain.objects.select_related("identity_provider_config").get(
                identity_provider_config__scim_slug=scim_slug
            )
        except (OrganizationDomain.DoesNotExist, OrganizationDomain.MultipleObjectsReturned):
            raise exceptions.AuthenticationFailed("Invalid organization domain")

        # Read the linked IdP config directly (the source of truth) rather than through the
        # empty-config fallback, so a domain with no config fails clearly here instead of falling
        # through to a misleading "Invalid bearer token" on a null hash below.
        #
        # The domain must also be verified: SCIM can be enabled on a config independently of any
        # domain (the config API has no verification gate), so re-check verification here to keep
        # provisioning gated behind a verified domain.
        config = domain.identity_provider_config
        if not domain.is_verified or config is None or not config.has_scim:
            raise exceptions.AuthenticationFailed("SCIM not configured for this domain")

        if not domain.organization.is_feature_available(AvailableFeature.SCIM):
            raise exceptions.AuthenticationFailed("Your organization does not have the required license to use SCIM")

        # Verify the bearer token matches the stored hashed token (sourced from the IdP config)
        if not check_password(token, config.scim_bearer_token):
            raise exceptions.AuthenticationFailed("Invalid bearer token")

        return (SCIMAuthToken(domain), domain)

    def _extract_scim_slug_from_path(self, path: str) -> Optional[str]:
        """
        Extract the IdP config slug from the SCIM URL path.
        Expected format: /scim/v2/{scim_slug}/Users or /scim/v2/{scim_slug}/Groups
        """
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "scim" and parts[1] == "v2":
            return parts[2]
        return None


@dataclass(frozen=True)
class ScimToken:
    # `plain` is shown to the user once. Only `hashed` is persisted.
    plain: str = field(repr=False)
    hashed: str


def generate_scim_token() -> ScimToken:
    """Generate a new SCIM bearer token."""
    plain_token = secrets.token_urlsafe(32)
    hashed_token = make_password(plain_token)
    return ScimToken(plain=plain_token, hashed=hashed_token)
