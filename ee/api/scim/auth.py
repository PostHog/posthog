import secrets
from dataclasses import dataclass, field
from typing import Optional

from django.contrib.auth.hashers import check_password, make_password

from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from posthog.constants import AvailableFeature
from posthog.models.identity_provider_config import IdentityProviderConfig


class SCIMAuthToken:
    """
    Wrapper class to make IdentityProviderConfig compatible with DRF's authentication system.
    DRF expects request.user to have is_authenticated property.
    """

    def __init__(self, config: IdentityProviderConfig):
        self.config = config
        self.is_authenticated = True
        self.is_active = True
        self.pk = None  # SCIM auth doesn't have a user PK
        self.id = None

    def __str__(self):
        return f"SCIMAuth({self.config.scim_slug})"


class SCIMBearerTokenAuthentication(BaseAuthentication):
    """
    SCIM authentication using bearer tokens.
    Each IdentityProviderConfig has its own SCIM bearer token and `scim_slug` for tenant isolation.
    """

    def authenticate(self, request: Request) -> Optional[tuple[SCIMAuthToken, IdentityProviderConfig]]:
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
            config = IdentityProviderConfig.objects.select_related("organization").get(scim_slug=scim_slug)
        except IdentityProviderConfig.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid SCIM slug")

        hashed_token = config.scim_bearer_token
        # SCIM stays gated behind domain verification, which the config API doesn't check. Any of the
        # config's verified domains admits the request — it names a config, not one of the domains
        # behind it — so the config, and its organization, is what scopes the request from here.
        if (
            not config.has_scim
            or not hashed_token
            or not config.organization_domains.filter(verified_at__isnull=False).exists()
        ):
            raise exceptions.AuthenticationFailed("SCIM is not enabled on a verified domain for this configuration")

        if not config.organization.is_feature_available(AvailableFeature.SCIM):
            raise exceptions.AuthenticationFailed("Your organization does not have the required license to use SCIM")

        if not check_password(token, hashed_token):
            raise exceptions.AuthenticationFailed("Invalid bearer token")

        return (SCIMAuthToken(config), config)

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
