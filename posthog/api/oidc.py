from functools import cached_property
from typing import Any, cast
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError

import jwt
from requests import RequestException, Response
from social_core.backends.open_id_connect import OpenIdConnectAuth
from social_core.exceptions import AuthConnectionError, AuthFailed, AuthMissingParameter, AuthTokenError

from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.models.identity_provider_config import IdentityProviderConfig
from posthog.security.pinned_requests import SSRFBlockedError, pinned_session

BasicAuthCredentials = tuple[str, str]


@frozen
class OIDCClientCredentials:
    client_id: str
    client_secret: str

    def as_tuple(self) -> BasicAuthCredentials:
        return self.client_id, self.client_secret


class MultitenantOIDCAuth(OpenIdConnectAuth):
    DEFAULT_USE_PKCE = True
    JWT_DECODE_OPTIONS = {"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]}

    @cached_property
    def identity_provider_config(self) -> IdentityProviderConfig:
        config_id = self.strategy.session_get("oidc_config_id")
        email = self.strategy.session_get("oidc_email")
        organization_id = self.strategy.session_get("oidc_organization_id")
        if not isinstance(email, str) or organization_id is None:
            raise AuthFailed(self, "OIDC email is not available.")
        try:
            config = (
                IdentityProviderConfig.objects.get_queryset()
                .oidc_for_email(email)
                .select_related("organization")
                .get(id=config_id, organization_id=organization_id)
            )
        except (IdentityProviderConfig.DoesNotExist, ValidationError, ValueError):
            raise AuthFailed(self, "OIDC configuration is not available.")
        if not config.has_oidc or not config.organization.is_feature_available(AvailableFeature.OIDC):
            raise AuthFailed(self, "OIDC is not available for this organization.")
        return config

    def auth_url(self) -> str:
        email = self.data.get("email")
        if not email or not isinstance(email, str):
            raise AuthMissingParameter(self, "email")
        configs = [
            config
            for config in IdentityProviderConfig.objects.get_queryset()
            .oidc_for_email(email)
            .select_related("organization")
            if config.has_oidc and config.organization.is_feature_available(AvailableFeature.OIDC)
        ]
        if len(configs) != 1:
            raise AuthFailed(self, "OIDC requires one configured identity provider for this email domain.")
        self.strategy.session_set("oidc_config_id", str(configs[0].id))
        self.strategy.session_set("oidc_email", email)
        self.strategy.session_set("oidc_organization_id", str(configs[0].organization_id))
        return super().auth_url()

    def oidc_endpoint(self) -> str:
        return self.identity_provider_config.oidc_issuer_url.rstrip("/")

    def oidc_config(self) -> dict[str, Any]:
        return self.discovery_document

    @cached_property
    def discovery_document(self) -> dict[str, Any]:
        document = self.get_json(f"{self.oidc_endpoint()}/.well-known/openid-configuration")
        if document.get("issuer") != self.identity_provider_config.oidc_issuer_url:
            raise AuthFailed(self, "The OIDC discovery issuer does not match the configured issuer.")
        for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            endpoint = document.get(field)
            if not isinstance(endpoint, str) or urlsplit(endpoint).scheme != "https":
                raise AuthFailed(self, "OIDC discovery requires HTTPS endpoints.")
        return document

    def _get_client_credentials(self) -> OIDCClientCredentials:
        config = self.identity_provider_config
        return OIDCClientCredentials(
            client_id=config.oidc_client_id,
            client_secret=config.oidc_credentials["client_secret"],
        )

    def get_key_and_secret(self) -> BasicAuthCredentials:
        return self._get_client_credentials().as_tuple()

    def get_jwks_keys(self) -> list[dict[str, Any]]:
        return self.get_remote_jwks_keys()

    def find_valid_key(self, id_token: str) -> dict[str, Any] | None:
        key_id = jwt.get_unverified_header(id_token).get("kid")
        keys = [
            {**key, "alg": "RS256"}
            for key in self.get_jwks_keys()
            if key.get("kty") == "RSA"
            and key.get("alg", "RS256") == "RS256"
            and key.get("use", "sig") == "sig"
            and (key_id is None or key.get("kid") == key_id)
        ]
        return keys[0] if len(keys) == 1 else None

    def validate_claims(self, id_token: dict[str, Any]) -> None:
        client_id = self.identity_provider_config.oidc_client_id
        authorized_party = id_token.get("azp")
        audiences = id_token.get("aud")
        if (authorized_party is not None and authorized_party != client_id) or (
            isinstance(audiences, list) and len(audiences) > 1 and authorized_party != client_id
        ):
            raise AuthTokenError(self, "The OIDC authorized party does not match the client ID.")
        super().validate_claims(id_token)

    def request(self, url: str, method: str = "GET", *args: Any, **kwargs: Any) -> Response:
        if urlsplit(url).scheme != "https":
            raise AuthFailed(self, "OIDC requires HTTPS endpoints.")
        kwargs["timeout"] = 10
        kwargs["allow_redirects"] = False
        try:
            with pinned_session(url) as session:
                response = session.request(method, url, *args, **kwargs)
                if response.is_redirect:
                    raise AuthFailed(self, "OIDC endpoint redirects are not supported.")
                response.raise_for_status()
                return response
        except (RequestException, SSRFBlockedError) as error:
            raise AuthConnectionError(self) from error

    def user_data(self, access_token: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        id_token = cast(dict[str, Any] | None, self.id_token)
        if id_token is None:
            raise AuthFailed(self, "OIDC did not return a valid ID token.")
        userinfo = super().user_data(access_token, *args, **kwargs)
        if not isinstance(userinfo, dict) or userinfo.get("sub") != id_token.get("sub"):
            raise AuthFailed(self, "The OIDC user does not match the ID token.")
        email = userinfo.get("email")
        if userinfo.get("email_verified") is not True or not isinstance(email, str):
            raise AuthFailed(self, "OIDC requires a verified email address from the identity provider.")
        if not (
            IdentityProviderConfig.objects.get_queryset()
            .oidc_for_email(email)
            .filter(id=self.identity_provider_config.id)
            .exists()
        ):
            raise AuthFailed(self, "The OIDC email domain does not belong to this identity provider configuration.")
        return userinfo

    def get_user_id(self, details: dict[str, Any], response: dict[str, Any]) -> str:
        return f"{self.identity_provider_config.id}:{response['sub']}"

    def extra_data(
        self, user: Any, uid: str, response: dict[str, Any], details: dict[str, Any], *args: Any, **kwargs: Any
    ) -> dict:
        return {}
