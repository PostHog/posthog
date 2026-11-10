import secrets
from dataclasses import dataclass, field
from typing import Optional

from django.contrib.auth.hashers import check_password, make_password

from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from posthog.constants import AvailableFeature
from posthog.ip_restrictions import enforce_ip_restrictions
from posthog.models.activity_logging.utils import ActivityCredentialMixin
from posthog.models.identity_provider_config import IdentityProviderConfig
from posthog.models.utils import hash_key_value


class SCIMAuthToken:
    """
    Wrapper class to make IdentityProviderConfig compatible with DRF's authentication system.
    DRF expects request.user to have is_authenticated property.
    """

    def __init__(self, config: IdentityProviderConfig):
        self.config = config
        self.current_organization_id = config.organization_id
        self.is_authenticated = True
        self.is_active = True
        self.pk = None  # SCIM auth doesn't have a user PK
        self.id = None

    def __str__(self):
        return f"SCIMAuth({self.config.scim_slug})"


class SCIMBearerTokenAuthentication(ActivityCredentialMixin, BaseAuthentication):
    """
    Authenticates against the SCIM bearer token, which identifies the tenant either together with
    the `scim_slug` in the URL (`/scim/v2/{scim_slug}/Users`) or on its own (`/scim/v2/Users`).
    Both URL shapes are supported permanently.
    """

    activity_credential_type = "scim"

    def authenticate(self, request: Request) -> Optional[tuple[SCIMAuthToken, IdentityProviderConfig]]:
        if not request.path.startswith("/scim/"):
            return None

        auth_header = request.headers.get("authorization", "")
        token = auth_header[7:] if auth_header.startswith("Bearer ") else ""

        if not token:
            raise exceptions.NotAuthenticated("Bearer token required for SCIM endpoints")

        config = self._resolve_config(token, self._extract_scim_slug_from_path(request.path))

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

        # Tokens issued before `scim_token_digest` existed can only be resolved by slug, because the
        # stored `scim_bearer_token` is salted and the plaintext was shown once. Backfilling the
        # digest from this verified request makes the slug-free URL work without a token rotation.
        if not config.scim_token_digest:
            IdentityProviderConfig.objects.filter(pk=config.pk, scim_token_digest__isnull=True).update(
                scim_token_digest=hash_key_value(token)
            )

        user = SCIMAuthToken(config)
        enforce_ip_restrictions(request, user, self)
        self.record_activity_actor(None, str(config.id))
        return (user, config)

    def _resolve_config(self, token: str, scim_slug: Optional[str]) -> IdentityProviderConfig:
        """
        Find the tenant's config from the slug in the URL, or, on the slug-free `/scim/v2/*` routes,
        from the bearer token alone.
        """
        configs = IdentityProviderConfig.objects.select_related("organization")

        if scim_slug:
            try:
                # nosemgrep: idor-lookup-without-org (SCIM bearer token auth, config slug is tenant identifier)
                return configs.get(scim_slug=scim_slug)
            except IdentityProviderConfig.DoesNotExist:
                raise exceptions.AuthenticationFailed("Invalid SCIM slug")

        # `check_password` below is still what verifies the token. The digest is an unsalted SHA-256
        # (the scheme personal API keys use), which is only safe to match on because a SCIM token is
        # 256 bits of `secrets` output, so it cannot be recovered from the digest.
        try:
            return configs.get(scim_token_digest=hash_key_value(token))
        except IdentityProviderConfig.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid bearer token")

    def _extract_scim_slug_from_path(self, path: str) -> Optional[str]:
        """
        Extract the IdP config slug from the SCIM URL path.
        Expected format: /scim/v2/{scim_slug}/Users or /scim/v2/{scim_slug}/Groups

        The slug-free routes (`/scim/v2/Users`, `/scim/v2/Schemas`, ...) have no fourth segment, so
        their third segment is a resource name, not a slug.
        """
        parts = path.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "scim" and parts[1] == "v2":
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
