import base64
import hashlib
from datetime import timedelta
from typing import Optional, cast
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized
from rest_framework import status

from posthog.api.oauth import OAuthAuthorizationSerializer
from posthog.models.oauth import (
    OAuthAccessToken,
    OAuthApplication,
    OAuthApplicationAccessLevel,
    OAuthGrant,
    OAuthRefreshToken,
)
from posthog.models.team.team import Team
import pytest


def generate_rsa_key() -> str:
    # Generate a new RSA private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=4096,
    )
    # Serialize the private key to PEM format
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )

    return pem.decode("utf-8")


@override_settings(
    OAUTH2_PROVIDER={
        **settings.OAUTH2_PROVIDER,
        "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
    }
)
class TestOAuthAPI(APIBaseTest):
    def setUp(self):
        super().setUp()

        self.confidential_application = OAuthApplication.objects.create(
            name="Test Confidential App",
            client_id="test_confidential_client_id",
            client_secret="test_confidential_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            user=self.user,
            hash_client_secret=True,
            algorithm="RS256",
        )

        self.public_application = OAuthApplication.objects.create(
            name="Test Public App",
            client_id="test_public_client_id",
            client_secret="test_public_client_secret",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            user=self.user,
            hash_client_secret=True,
            algorithm="RS256",
        )

        self.code_verifier = "test_challenge"

        self.client.force_login(self.user)

    @property
    def code_challenge(self) -> str:
        """
        Given a PKCE code_verifier, return the URL-safe base64-encoded
        SHA256 digest (the code_challenge), without padding.

        This is the job of a oauth2 client library, but we use it in the tests to generate the code_challenge
        """
        digest = hashlib.sha256(self.code_verifier.encode("utf-8")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").replace("=", "")
        return code_challenge

    @property
    def base_authorization_url(self) -> str:
        return f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

    @property
    def base_authorization_post_body(self) -> dict:
        return {
            "client_id": "test_confidential_client_id",
            "redirect_uri": "https://example.com/callback",
            "response_type": "code",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "allow": True,
            "access_level": OAuthApplicationAccessLevel.ALL.value,
            "scoped_organizations": [],
            "scoped_teams": [],
            "scope": "openid",
        }

    @property
    def base_token_body(self) -> dict:
        return {
            "grant_type": "authorization_code",
            "client_id": "test_confidential_client_id",
            "client_secret": "test_confidential_client_secret",
            "redirect_uri": "https://example.com/callback",
            "code_verifier": self.code_verifier,
        }

    @property
    def private_key(self) -> str:
        return str(settings.OAUTH2_PROVIDER["OIDC_RSA_PRIVATE_KEY"])

    @property
    def public_key(self) -> str:
        private_key_pem = self.private_key

        private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)

        public_key = private_key.public_key()

        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        return public_key_pem.decode("utf-8")

    def post(self, url: str, body: dict, headers: dict | None = None):
        return self.client.post(
            url, data=urlencode(body), content_type="application/x-www-form-urlencoded", headers=headers
        )

    def replace_param_in_url(self, url: str, param: str, value: Optional[str] = None) -> str:
        """
        Return `url` with the query parameter `param` replaced by `value`.
        If `value` is None, the parameter is removed entirely.
        """
        parts = urlparse(url)
        qs = parse_qs(parts.query, keep_blank_values=True)

        if value is None:
            qs.pop(param, None)
        else:
            qs[param] = [value]

        new_query = urlencode(qs, doseq=True)
        return urlunparse(parts._replace(query=new_query))

    def get_basic_auth_header(self, client_id: str, client_secret: str) -> str:
        return f"Basic {base64.b64encode(f'{client_id}:{client_secret}'.encode()).decode()}"

    def test_authorize_redirects_to_login_if_not_authenticated(self):
        self.client.logout()

        response = self.client.get(self.base_authorization_url)
        assert response.status_code == status.HTTP_302_FOUND
        assert f"/login?next=/oauth/authorize/" in response["Location"]

    def test_authorize_successful_with_required_params(self):
        response = self.client.get(self.base_authorization_url)
        assert response.status_code == status.HTTP_200_OK

    def test_authorize_missing_client_id(self):
        url = self.base_authorization_url

        url_without_client_id = self.replace_param_in_url(url, "client_id", None)

        response = self.client.get(url_without_client_id)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_request"
        assert response.json()["error_description"] == "Missing client_id parameter."

    def test_authorize_invalid_client_id(self):
        url = self.base_authorization_url

        url_without_client_id = self.replace_param_in_url(url, "client_id", "invalid_id")

        response = self.client.get(url_without_client_id)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_request"
        assert response.json()["error_description"] == "Invalid client_id parameter value."

    def test_authorize_missing_redirect_uri(self):
        # According to the spec, if the client has a single redirect URI, the authorization server does not require an
        # explicit redirect_uri parameter and can use the one provided by the application.
        url = self.base_authorization_url

        url_without_redirect_uri = self.replace_param_in_url(url, "redirect_uri", None)

        response = self.client.get(url_without_redirect_uri)

        assert response.status_code == status.HTTP_200_OK

    def test_authorize_rejects_if_missing_redirect_uri_and_multiple_redirect_uris(self):
        # According to the spec, if the client has multiple redirect URIs, the authorization server MUST require an
        # explicit redirect_uri parameter.
        url = self.base_authorization_url

        application = OAuthApplication.objects.create(
            name="Test Confidential App With Multiple Redirect URIs",
            client_id="test_confidential_client_id_multiple_redirect_uris",
            client_secret="test_confidential_client_secret_multiple_redirect_uris",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback https://example.com/callback2",
            algorithm="RS256",
        )

        url_without_redirect_uri = self.replace_param_in_url(url, "redirect_uri", None)

        url_with_client_id = self.replace_param_in_url(url_without_redirect_uri, "client_id", application.client_id)

        response = self.client.get(url_with_client_id)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_request"
        assert response.json()["error_description"] == "Missing redirect URI."

    def test_authorize_invalid_redirect_uri(self):
        url = self.base_authorization_url

        url_without_redirect_uri = self.replace_param_in_url(url, "redirect_uri", "http://invalid.com/callback")

        response = self.client.get(url_without_redirect_uri)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_request"
        assert response.json()["error_description"] == "Mismatching redirect URI."

    def test_authorize_fails_without_pkce(self):
        url = self.base_authorization_url

        url_without_code_challenge = self.replace_param_in_url(url, "code_challenge", None)

        response = self.client.get(url_without_code_challenge)

        assert response.status_code == status.HTTP_302_FOUND

        location = response["Location"]

        assert "error=invalid_request" in location
        assert "error_description=Code+challenge+required" in location

    def test_authorize_post_fails_if_not_authenticated(self):
        self.client.logout()

        response = self.post(
            "/oauth/authorize/",
            self.base_authorization_post_body,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @freeze_time("2025-01-01 00:00:00")
    def test_authorize_post_authorization_granted(self):
        response = self.client.post(
            "/oauth/authorize/",
            self.base_authorization_post_body,
        )

        assert response.status_code == status.HTTP_200_OK
        redirect_to = response.json()["redirect_to"]
        assert "code=" in redirect_to

        code = redirect_to.split("code=")[1].split("&")[0]

        grant = OAuthGrant.objects.get(code=code)

        assert grant.application == self.confidential_application
        assert grant.user == self.user
        assert grant.code == code
        assert grant.code_challenge == self.code_challenge
        assert grant.code_challenge_method == "S256"

        expiration_seconds = cast(int, settings.OAUTH2_PROVIDER["AUTHORIZATION_CODE_EXPIRE_SECONDS"])
        expiration_minutes = expiration_seconds / 60
        expected_expiration = timezone.now() + timedelta(minutes=expiration_minutes)
        assert grant.expires == expected_expiration

    def test_authorize_post_denied_authorization(self):
        response = self.client.post(
            "/oauth/authorize/",
            {
                **self.base_authorization_post_body,
                "allow": False,
            },
        )

        assert response.status_code == status.HTTP_200_OK

        redirect_to = response.json()["redirect_to"]
        assert redirect_to == "https://example.com/callback?error=access_denied"

    def test_cannot_get_token_with_invalid_code(self):
        data = {
            "grant_type": "authorization_code",
            "code": "invalid_code",
            "client_id": "test_confidential_client_id",
            "client_secret": "test_confidential_client_secret",
            "redirect_uri": "https://example.com/callback",
            "code_verifier": self.code_verifier,
        }

        response = self.post("/oauth/token/", data)

        # Assert the response
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_grant"

    @freeze_time("2025-01-01 00:00:00")
    def test_cannot_get_token_with_expired_code(self):
        expired_grant = OAuthGrant.objects.create(
            application=self.confidential_application,
            user=self.user,
            code="expired_code",
            code_challenge=self.code_challenge,
            code_challenge_method="S256",
            expires=timezone.now() - timedelta(minutes=1),
        )

        data = {
            "grant_type": "authorization_code",
            "code": expired_grant.code,
            "client_id": "test_confidential_client_id",
            "client_secret": "test_confidential_client_secret",
            "redirect_uri": "https://example.com/callback",
            "code_verifier": self.code_verifier,
        }

        response = self.post("/oauth/token/", data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_grant"

    def test_token_endpoint_missing_grant_type(self):
        response = self.post("/oauth/token/", {})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "unsupported_grant_type"

    def test_token_endpoint_invalid_grant(self):
        data = {
            "grant_type": "authorization_code",
            "code": "invalid_code",
            "client_id": "test_confidential_client_id",
            "client_secret": "test_confidential_client_secret",
            "redirect_uri": "https://example.com/callback",
            "code_verifier": self.code_verifier,
        }

        response = self.post("/oauth/token/", data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_grant"

    def test_full_oauth_flow(self):
        # 1. Get authorization request
        response = self.client.get(self.base_authorization_url)

        assert response.status_code == status.HTTP_200_OK

        # 2. Post authorization approval
        response = self.client.post(
            "/oauth/authorize/",
            self.base_authorization_post_body,
        )

        assert response.status_code == status.HTTP_200_OK

        # Extract authorization code from redirect URL
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        data = {
            **self.base_token_body,
            "code": code,
        }

        response = self.post("/oauth/token/", data)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert "access_token" in data
        assert "token_type" in data
        assert "expires_in" in data
        assert "refresh_token" in data
        assert "scope" in data
        assert "scoped_teams" in data
        assert "scoped_organizations" in data

        access_token = data["access_token"]
        refresh_token = data["refresh_token"]

        data = {"grant_type": "refresh_token", "refresh_token": refresh_token}

        authorization_header = self.get_basic_auth_header(
            "test_confidential_client_id", "test_confidential_client_secret"
        )

        response = self.post("/oauth/token/", data, headers={"Authorization": authorization_header})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert "access_token" in data
        assert "refresh_token" in data

        assert data["access_token"] != access_token
        assert data["refresh_token"] != refresh_token

    @freeze_time("2025-01-01 00:00:00")
    def test_token_endpoint_invalid_client_credentials(self):
        grant = OAuthGrant.objects.create(
            application=self.confidential_application,
            user=self.user,
            code="test_code",
            code_challenge=self.code_challenge,
            code_challenge_method="S256",
            expires=timezone.now() + timedelta(minutes=1),
        )

        data = {
            "grant_type": "client_credentials",
            "client_id": "test_confidential_client_id",
            "client_secret": "wrong_secret",
            "redirect_uri": "https://example.com/callback",
            "code_verifier": self.code_verifier,
            "code": grant.code,
        }

        response = self.post("/oauth/token/", data)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_invalid_scoped_organizations_with_all_access_level(self):
        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.ALL.value,
            "scoped_organizations": ["org1"],
            "scoped_teams": [1],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})

        assert not serializer.is_valid()
        assert "scoped_organizations" in serializer.errors
        assert serializer.errors["scoped_organizations"][0] == "scoped_organizations is not allowed when access_level is all"

    def test_invalid_scoped_teams_with_organization_access_level(self):
        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.ORGANIZATION.value,
            "scoped_organizations": ["org1"],
            "scoped_teams": [1],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})
        assert not serializer.is_valid()
        assert "scoped_teams" in serializer.errors
        assert serializer.errors["scoped_teams"][0] == "scoped_teams is not allowed when access_level is organization"

    def test_missing_scoped_organizations_with_organization_access_level(self):
        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.ORGANIZATION.value,
            "scoped_organizations": [],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})
        assert not serializer.is_valid()
        assert "scoped_organizations" in serializer.errors
        assert serializer.errors["scoped_organizations"][0] == "scoped_organizations is required when access_level is organization"

    def test_missing_scoped_teams_with_team_access_level(self):
        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.TEAM.value,
            "scoped_teams": [],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})
        assert not serializer.is_valid()
        assert "scoped_teams" in serializer.errors
        assert serializer.errors["scoped_teams"][0] == "scoped_teams is required when access_level is team"

    def test_full_oauth_flow_preserves_scoped_teams(self):
        scoped_teams = [self.team.id]

        authorization_data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.TEAM.value,
            "scoped_teams": scoped_teams,
        }

        response = self.client.post(
            "/oauth/authorize/",
            authorization_data,
        )

        assert response.status_code == status.HTTP_200_OK

        redirect_to = response.json()["redirect_to"]
        assert "code=" in redirect_to
        code = redirect_to.split("code=")[1].split("&")[0]

        assert code is not None

        grant = OAuthGrant.objects.get(code=code)

        assert grant.scoped_teams == scoped_teams

        token_data = {
            **self.base_token_body,
            "code": code,
        }

        token_response = self.post(
            "/oauth/token/",
            token_data,
        )

        assert token_response.status_code == status.HTTP_200_OK
        token_response_data = token_response.json()

        assert "access_token" in token_response_data
        assert "refresh_token" in token_response_data
        assert "scoped_teams" in token_response_data
        assert token_response_data["scoped_teams"] == scoped_teams

        access_token = OAuthAccessToken.objects.get(token=token_response_data["access_token"])

        assert access_token.scoped_teams == scoped_teams

        refresh_token = OAuthRefreshToken.objects.get(token=token_response_data["refresh_token"])

        assert refresh_token.scoped_teams == scoped_teams

        # refresh the access token
        refresh_token_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.confidential_application.client_id,
            "client_secret": "test_confidential_client_secret",
        }

        refresh_token_response = self.post("/oauth/token/", refresh_token_data)

        assert refresh_token_response.status_code == status.HTTP_200_OK
        refresh_token_response_data = refresh_token_response.json()

        assert "access_token" in refresh_token_response_data
        assert "refresh_token" in refresh_token_response_data
        assert "scoped_teams" in refresh_token_response_data
        assert refresh_token_response_data["scoped_teams"] == scoped_teams

        access_token = OAuthAccessToken.objects.get(token=refresh_token_response_data["access_token"])

        assert access_token.scoped_teams == scoped_teams

        refresh_token = OAuthRefreshToken.objects.get(token=refresh_token_response_data["refresh_token"])

        assert refresh_token.scoped_teams == scoped_teams

    def test_full_oauth_flow_preserves_scoped_organizations(self):
        scoped_organizations = [str(self.organization.id)]

        authorization_data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.ORGANIZATION.value,
            "scoped_organizations": scoped_organizations,
        }

        response = self.client.post(
            "/oauth/authorize/",
            authorization_data,
        )

        assert response.status_code == status.HTTP_200_OK

        redirect_to = response.json()["redirect_to"]
        assert "code=" in redirect_to
        code = redirect_to.split("code=")[1].split("&")[0]

        assert code is not None

        grant = OAuthGrant.objects.get(code=code)

        assert grant.scoped_organizations == scoped_organizations

        token_data = {
            **self.base_token_body,
            "code": code,
        }

        token_response = self.post(
            "/oauth/token/",
            token_data,
        )

        assert token_response.status_code == status.HTTP_200_OK
        token_response_data = token_response.json()

        assert "scoped_organizations" in token_response_data
        assert token_response_data["scoped_organizations"] == scoped_organizations

        access_token = OAuthAccessToken.objects.get(token=token_response_data["access_token"])

        assert access_token.scoped_organizations == scoped_organizations

        refresh_token = OAuthRefreshToken.objects.get(token=token_response_data["refresh_token"])

        assert refresh_token.scoped_organizations == scoped_organizations

        refresh_token_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.confidential_application.client_id,
            "client_secret": "test_confidential_client_secret",
        }

        refresh_token_response = self.post("/oauth/token/", refresh_token_data)

        assert refresh_token_response.status_code == status.HTTP_200_OK
        refresh_token_response_data = refresh_token_response.json()

        assert "access_token" in refresh_token_response_data
        assert "refresh_token" in refresh_token_response_data
        assert "scoped_organizations" in refresh_token_response_data
        assert refresh_token_response_data["scoped_organizations"] == scoped_organizations

        access_token = OAuthAccessToken.objects.get(token=refresh_token_response_data["access_token"])

        assert access_token.scoped_organizations == scoped_organizations

        refresh_token = OAuthRefreshToken.objects.get(token=refresh_token_response_data["refresh_token"])

        assert refresh_token.scoped_organizations == scoped_organizations

    # OIDC tests

    def test_full_oidc_flow(self):
        data_with_openid = {
            **self.base_authorization_post_body,
            "scope": "openid email profile experiment:read",
        }

        response = self.client.post("/oauth/authorize/", data_with_openid)

        assert response.status_code == status.HTTP_200_OK
        redirect_to = response.json().get("redirect_to", "")
        assert "code=" in redirect_to

        code = redirect_to.split("code=")[1].split("&")[0]

        token_data = {
            **self.base_token_body,
            "code": code,
        }

        token_response = self.post("/oauth/token/", token_data)

        assert token_response.status_code == status.HTTP_200_OK
        token_response_data = token_response.json()

        assert "id_token" in token_response_data

        id_token = token_response_data["id_token"]

        decoded_token = jwt.decode(
            id_token, self.public_key, algorithms=["RS256"], audience=self.confidential_application.client_id
        )

        # Verify the claims
        assert decoded_token["sub"] == str(self.user.uuid)
        assert decoded_token["email"] == self.user.email
        assert decoded_token["email_verified"] == (self.user.is_email_verified or False)
        assert decoded_token["given_name"] == self.user.first_name
        assert decoded_token["family_name"] == self.user.last_name

        # Fetch /oauth/userinfo
        userinfo_response = self.client.get(
            "/oauth/userinfo/", headers={"Authorization": f"Bearer {token_response_data['access_token']}"}
        )
        assert userinfo_response.status_code == status.HTTP_200_OK
        userinfo_data = userinfo_response.json()

        # Verify the response matches the decoded token
        assert userinfo_data["sub"] == str(self.user.uuid)
        assert userinfo_data["email"] == self.user.email
        assert userinfo_data["email_verified"] == (self.user.is_email_verified or False)
        assert userinfo_data["given_name"] == self.user.first_name
        assert userinfo_data["family_name"] == self.user.last_name

    def test_jwks_endpoint_returns_valid_jwks(self):
        response = self.client.get("/.well-known/jwks.json")
        assert response.status_code == status.HTTP_200_OK

        jwks = response.json()
        assert "keys" in jwks

        jwks = response.json()

        key_data = jwks["keys"][0]
        public_numbers = rsa.RSAPublicNumbers(
            e=int.from_bytes(base64.urlsafe_b64decode(key_data["e"] + "=="), "big"),
            n=int.from_bytes(base64.urlsafe_b64decode(key_data["n"] + "=="), "big"),
        )

        public_key = public_numbers.public_key()

        public_key_pem_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        public_key_pem_str = public_key_pem_bytes.decode("utf-8")

        assert public_key_pem_str == self.public_key

    def test_id_token_not_returned_without_openid_scope(self):
        data_without_openid = {
            **self.base_authorization_post_body,
            "scope": "experiment:read action:write",
        }

        response = self.client.post("/oauth/authorize/", data_without_openid)

        assert response.status_code == status.HTTP_200_OK
        redirect_to = response.json().get("redirect_to", "")
        assert "code=" in redirect_to

        code = redirect_to.split("code=")[1].split("&")[0]

        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "test_confidential_client_id",
            "client_secret": "test_confidential_client_secret",
            "redirect_uri": "https://example.com/callback",
            "code_verifier": self.code_verifier,
        }

        token_response = self.post("/oauth/token/", token_data)

        assert token_response.status_code == status.HTTP_200_OK
        token_response_data = token_response.json()

        assert "access_token" in token_response_data
        assert "refresh_token" in token_response_data

        assert "id_token" not in token_response_data

    # Revoking tokens

    @freeze_time("2025-01-01 00:00:00")
    def test_revoke_refresh_token_for_application(self):
        token_value = f"test_refresh_token_to_revoke"

        refresh_token = OAuthRefreshToken.objects.create(
            application=self.confidential_application,
            user=self.user,
            token=token_value,
        )

        body = {
            "token": token_value,
            "token_type_hint": "refresh_token",
            "client_id": self.confidential_application.client_id,
            "client_secret": "test_confidential_client_secret",
        }

        response = self.post("/oauth/revoke/", body)

        assert response.status_code == status.HTTP_200_OK

        refresh_token.refresh_from_db()

        assert refresh_token.revoked == timezone.now()

    def test_revoke_refresh_token_for_confidential_application_without_client_secret_fails(self):
        token_value = f"test_refresh_token_to_revoke_without_client_secret"

        refresh_token = OAuthRefreshToken.objects.create(
            application=self.confidential_application,
            user=self.user,
            token=token_value,
        )

        body = {
            "token": token_value,
            "token_type_hint": "refresh_token",
            "client_id": self.confidential_application.client_id,
        }

        response = self.post("/oauth/revoke/", body)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        refresh_token.refresh_from_db()

        assert refresh_token.revoked is None

    @freeze_time("2025-01-01 00:00:00")
    def test_revoke_refresh_token_for_public_application_without_client_secret(self):
        token_value = f"test_refresh_token_to_revoke_without_client_secret"

        refresh_token = OAuthRefreshToken.objects.create(
            application=self.public_application,
            user=self.user,
            token=token_value,
        )

        body = {
            "token": token_value,
            "token_type_hint": "refresh_token",
            "client_id": self.public_application.client_id,
        }

        response = self.post("/oauth/revoke/", body)

        assert response.status_code == status.HTTP_200_OK

        refresh_token.refresh_from_db()

        assert refresh_token.revoked == timezone.now()

    def test_serializer_requires_user_in_context(self):
        data = {
            **self.base_authorization_post_body,
        }

        with pytest.raises(ValueError) as cm:
            OAuthAuthorizationSerializer(data=data)
        assert str(cm.value) == "OAuthAuthorizationSerializer requires 'user' in context"

        with pytest.raises(ValueError) as cm:
            OAuthAuthorizationSerializer(data=data, context={})
        assert str(cm.value) == "OAuthAuthorizationSerializer requires 'user' in context"

        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})
        assert serializer.is_valid()

    def test_cannot_scope_to_unauthorized_organization(self):
        from posthog.models import Organization

        other_org = Organization.objects.create(name="Other Organization")

        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.ORGANIZATION.value,
            "scoped_organizations": [str(other_org.id)],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})

        assert not serializer.is_valid()
        assert "scoped_organizations" in serializer.errors
        assert f"You must be a member of organization '{other_org.id}'" in str(serializer.errors["scoped_organizations"][0])

    def test_cannot_scope_to_unauthorized_team(self):
        from posthog.models import Organization

        other_org = Organization.objects.create(name="Other Organization")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.TEAM.value,
            "scoped_teams": [other_team.id],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})

        assert not serializer.is_valid()
        assert "scoped_teams" in serializer.errors
        assert f"You must be a member of team '{other_team.id}'" in str(serializer.errors["scoped_teams"][0])

    def test_malformed_organization_uuid_rejected(self):
        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.ORGANIZATION.value,
            "scoped_organizations": ["invalid-uuid", "not-a-uuid-at-all"],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})

        assert not serializer.is_valid()
        assert "scoped_organizations" in serializer.errors
        assert "Invalid organization UUID" in str(serializer.errors["scoped_organizations"][0])

    def test_nonexistent_team_rejected(self):
        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.TEAM.value,
            "scoped_teams": [99999, 88888],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})

        assert not serializer.is_valid()
        assert "scoped_teams" in serializer.errors
        assert "do not exist" in str(serializer.errors["scoped_teams"][0])

    def test_authorization_code_reuse_prevented(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        assert response.status_code == status.HTTP_200_OK

        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]
        token_data = {**self.base_token_body, "code": code}

        response1 = self.post("/oauth/token/", token_data)
        assert response1.status_code == status.HTTP_200_OK

        response2 = self.post("/oauth/token/", token_data)
        assert response2.status_code == status.HTTP_400_BAD_REQUEST
        assert response2.json()["error"] == "invalid_grant"

    def test_pkce_code_verifier_validation(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        assert response.status_code == status.HTTP_200_OK

        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_data = {**self.base_token_body, "code": code, "code_verifier": "wrong_verifier"}

        response = self.post("/oauth/token/", token_data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_grant"

    def test_redirect_uri_exact_match_required(self):
        malicious_data = {**self.base_authorization_post_body, "redirect_uri": "https://example.com/callback/malicious"}

        response = self.client.post("/oauth/authorize/", malicious_data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_scope_persistence_through_refresh(self):
        scoped_data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.TEAM.value,
            "scoped_teams": [self.team.id],
        }

        response = self.client.post("/oauth/authorize/", scoped_data)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post("/oauth/token/", {**self.base_token_body, "code": code})
        refresh_token = token_response.json()["refresh_token"]

        for _ in range(3):
            refresh_data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.confidential_application.client_id,
                "client_secret": "test_confidential_client_secret",
            }

            refresh_response = self.post("/oauth/token/", refresh_data)
            assert refresh_response.status_code == status.HTTP_200_OK

            new_access_token = refresh_response.json()["access_token"]
            db_token = OAuthAccessToken.objects.get(token=new_access_token)
            assert db_token.scoped_teams == [self.team.id]

            refresh_token = refresh_response.json()["refresh_token"]

    def test_revoked_refresh_token_invalidates_access_tokens(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post("/oauth/token/", {**self.base_token_body, "code": code})
        access_token = token_response.json()["access_token"]
        refresh_token = token_response.json()["refresh_token"]

        userinfo_response = self.client.get("/oauth/userinfo/", headers={"Authorization": f"Bearer {access_token}"})
        assert userinfo_response.status_code == status.HTTP_200_OK

        revoke_data = {
            "token": refresh_token,
            "token_type_hint": "refresh_token",
            "client_id": self.confidential_application.client_id,
            "client_secret": "test_confidential_client_secret",
        }

        revoke_response = self.post("/oauth/revoke/", revoke_data)
        assert revoke_response.status_code == status.HTTP_200_OK

        db_refresh_token = OAuthRefreshToken.objects.get(token=refresh_token)
        assert db_refresh_token.revoked is not None

        userinfo_response_after_revoke = self.client.get(
            "/oauth/userinfo/", headers={"Authorization": f"Bearer {access_token}"}
        )
        assert userinfo_response_after_revoke.status_code == status.HTTP_401_UNAUTHORIZED

    def test_client_credentials_required_for_confidential_clients(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_data_no_secret = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "test_confidential_client_id",
            "redirect_uri": "https://example.com/callback",
            "code_verifier": self.code_verifier,
        }

        response = self.post("/oauth/token/", token_data_no_secret)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_wrong_client_credentials_rejected(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_data_wrong_secret = {
            **self.base_token_body,
            "code": code,
            "client_secret": "wrong_secret",
        }

        response = self.post("/oauth/token/", token_data_wrong_secret)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cannot_use_authorization_code_with_different_client(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_data_different_client = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "test_public_client_id",
            "client_secret": "test_public_client_secret",
            "redirect_uri": "https://example.com/callback",
            "code_verifier": self.code_verifier,
        }

        response = self.post("/oauth/token/", token_data_different_client)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_grant"

    @freeze_time("2025-01-01 00:00:00")
    def test_refresh_token_rotation_invalidates_old_token(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post("/oauth/token/", {**self.base_token_body, "code": code})
        old_refresh_token = token_response.json()["refresh_token"]

        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": old_refresh_token,
            "client_id": self.confidential_application.client_id,
            "client_secret": "test_confidential_client_secret",
        }

        refresh_response = self.post("/oauth/token/", refresh_data)
        assert refresh_response.status_code == status.HTTP_200_OK
        new_refresh_token = refresh_response.json()["refresh_token"]

        assert old_refresh_token != new_refresh_token

        # Within grace period, old token should still work and return the same new tokens
        retry_old_token_within_grace = self.post("/oauth/token/", refresh_data)
        assert retry_old_token_within_grace.status_code == status.HTTP_200_OK
        assert retry_old_token_within_grace.json()["refresh_token"] == new_refresh_token

        # After grace period, old token should be invalid
        with freeze_time("2025-01-01 00:03:00"):  # 3 minutes later, beyond grace period
            retry_old_token_after_grace = self.post("/oauth/token/", refresh_data)
            assert retry_old_token_after_grace.status_code == status.HTTP_400_BAD_REQUEST
            assert retry_old_token_after_grace.json()["error"] == "invalid_grant"

    def test_mixed_scoped_access_levels_rejected(self):
        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.ORGANIZATION.value,
            "scoped_organizations": [str(self.organization.id)],
            "scoped_teams": [self.team.id],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})

        assert not serializer.is_valid()
        assert "scoped_teams" in serializer.errors

    def test_application_isolation_different_users(self):
        from posthog.models import Organization, OrganizationMembership, User

        other_org = Organization.objects.create(name="Other Org")
        other_user = User.objects.create_user(email="other@test.com", password="password", first_name="Other")
        OrganizationMembership.objects.create(user=other_user, organization=other_org)

        self.client.force_login(other_user)

        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        assert response.status_code == status.HTTP_200_OK

        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]
        grant = OAuthGrant.objects.get(code=code)
        assert grant.user == other_user
        assert grant.user != self.user

    def test_authorization_code_expires_correctly(self):
        with freeze_time("2025-01-01 00:00:00") as frozen_time:
            response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
            code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

            frozen_time.tick(delta=timedelta(minutes=6))

            token_data = {**self.base_token_body, "code": code}
            response = self.post("/oauth/token/", token_data)
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert response.json()["error"] == "invalid_grant"

    def test_public_client_pkce_enforcement(self):
        public_auth_data = {
            "client_id": "test_public_client_id",
            "redirect_uri": "https://example.com/callback",
            "response_type": "code",
            "allow": True,
            "access_level": OAuthApplicationAccessLevel.ALL.value,
            "scoped_organizations": [],
            "scoped_teams": [],
            "scope": "openid",
        }

        response = self.client.post("/oauth/authorize/", public_auth_data)
        assert response.status_code == status.HTTP_200_OK
        redirect_to = response.json()["redirect_to"]
        assert "error=invalid_request" in redirect_to

    def test_invalid_grant_type_rejected(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_data = {
            **self.base_token_body,
            "code": code,
            "grant_type": "password",
        }

        response = self.post("/oauth/token/", token_data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_request"

    def test_userinfo_endpoint_requires_valid_token(self):
        response = self.client.get("/oauth/userinfo/", headers={"Authorization": "Bearer invalid_token"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_userinfo_endpoint_with_expired_token(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post("/oauth/token/", {**self.base_token_body, "code": code})
        access_token = token_response.json()["access_token"]

        db_token = OAuthAccessToken.objects.get(token=access_token)
        db_token.expires = timezone.now() - timedelta(hours=1)
        db_token.save()

        response = self.client.get("/oauth/userinfo/", headers={"Authorization": f"Bearer {access_token}"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_redirect_uri_with_query_params_handled_safely(self):
        auth_data = {
            **self.base_authorization_post_body,
            "redirect_uri": "https://example.com/callback?redirect=https://evil.com",
        }

        response = self.client.post("/oauth/authorize/", auth_data)

        response_data = response.json()
        redirect_to = response_data.get("redirect_to", "")

        assert redirect_to.startswith("https://example.com/callback")
        assert "https://evil.com" not in redirect_to.split("?")[0]

    def test_authorization_code_cannot_be_used_across_different_applications(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        assert response.status_code == status.HTTP_200_OK

        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_data_wrong_app = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "test_public_client_id",
            "client_secret": "test_public_client_secret",
            "redirect_uri": "https://example.com/callback",
            "code_verifier": self.code_verifier,
        }

        response = self.post("/oauth/token/", token_data_wrong_app)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_grant"

    def test_pkce_strictly_enforced_for_public_clients(self):
        public_auth_data_no_pkce = {
            "client_id": "test_public_client_id",
            "redirect_uri": "https://example.com/callback",
            "response_type": "code",
            "allow": True,
            "access_level": OAuthApplicationAccessLevel.ALL.value,
            "scoped_organizations": [],
            "scoped_teams": [],
            "scope": "openid",
        }

        response = self.client.post("/oauth/authorize/", public_auth_data_no_pkce)
        assert response.status_code == status.HTTP_200_OK
        redirect_to = response.json()["redirect_to"]
        assert "error=invalid_request" in redirect_to
        assert "Code+challenge+required" in redirect_to

    def test_public_client_full_oauth_flow(self):
        # Public client authorization with PKCE
        public_auth_url = f"/oauth/authorize/?client_id=test_public_client_id&redirect_uri=https://example.com/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(public_auth_url)
        assert response.status_code == status.HTTP_200_OK

        # Post authorization approval for public client
        public_auth_data = {
            "client_id": "test_public_client_id",
            "redirect_uri": "https://example.com/callback",
            "response_type": "code",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "allow": True,
            "access_level": OAuthApplicationAccessLevel.ALL.value,
            "scoped_organizations": [],
            "scoped_teams": [],
            "scope": "openid",
        }

        response = self.client.post("/oauth/authorize/", public_auth_data)
        assert response.status_code == status.HTTP_200_OK

        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        # Token exchange for public client (no client secret)
        public_token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "test_public_client_id",
            "redirect_uri": "https://example.com/callback",
            "code_verifier": self.code_verifier,
        }

        token_response = self.post("/oauth/token/", public_token_data)
        assert token_response.status_code == status.HTTP_200_OK

        # Verify we get all expected tokens
        token_data = token_response.json()
        assert "access_token" in token_data
        assert "refresh_token" in token_data
        assert "token_type" in token_data
        assert "expires_in" in token_data

    def test_public_client_refresh_token_flow(self):
        # Complete initial OAuth flow for public client
        public_auth_data = {
            "client_id": "test_public_client_id",
            "redirect_uri": "https://example.com/callback",
            "response_type": "code",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "allow": True,
            "access_level": OAuthApplicationAccessLevel.ALL.value,
            "scoped_organizations": [],
            "scoped_teams": [],
            "scope": "openid",
        }

        response = self.client.post("/oauth/authorize/", public_auth_data)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post(
            "/oauth/token/",
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": "test_public_client_id",
                "redirect_uri": "https://example.com/callback",
                "code_verifier": self.code_verifier,
            },
        )

        refresh_token = token_response.json()["refresh_token"]

        # Use refresh token (public client doesn't need client secret)
        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": "test_public_client_id",
        }

        refresh_response = self.post("/oauth/token/", refresh_data)
        assert refresh_response.status_code == status.HTTP_200_OK

        refresh_response_data = refresh_response.json()
        assert "access_token" in refresh_response_data
        assert "refresh_token" in refresh_response_data

        # Verify token rotation occurred
        assert refresh_response_data["refresh_token"] != refresh_token

    def test_public_client_cannot_use_client_secret_authentication(self):
        # Complete initial OAuth flow for public client
        public_auth_data = {
            "client_id": "test_public_client_id",
            "redirect_uri": "https://example.com/callback",
            "response_type": "code",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "allow": True,
            "access_level": OAuthApplicationAccessLevel.ALL.value,
            "scoped_organizations": [],
            "scoped_teams": [],
            "scope": "openid",
        }

        response = self.client.post("/oauth/authorize/", public_auth_data)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        # Try to use client secret with public client (should still work but secret is ignored)
        token_response = self.post(
            "/oauth/token/",
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": "test_public_client_id",
                "client_secret": "test_public_client_secret",  # This should be ignored
                "redirect_uri": "https://example.com/callback",
                "code_verifier": self.code_verifier,
            },
        )

        # Public client should still work even with client_secret provided
        assert token_response.status_code == status.HTTP_200_OK

    def test_public_client_pkce_code_verifier_validation(self):
        # Complete authorization for public client
        public_auth_data = {
            "client_id": "test_public_client_id",
            "redirect_uri": "https://example.com/callback",
            "response_type": "code",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "allow": True,
            "access_level": OAuthApplicationAccessLevel.ALL.value,
            "scoped_organizations": [],
            "scoped_teams": [],
            "scope": "openid",
        }

        response = self.client.post("/oauth/authorize/", public_auth_data)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        # Try to exchange code with wrong code_verifier
        token_response = self.post(
            "/oauth/token/",
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": "test_public_client_id",
                "redirect_uri": "https://example.com/callback",
                "code_verifier": "wrong_verifier",
            },
        )

        assert token_response.status_code == status.HTTP_400_BAD_REQUEST
        assert token_response.json()["error"] == "invalid_grant"

    def test_public_client_missing_pkce_fails_token_exchange(self):
        # Complete authorization for public client
        public_auth_data = {
            "client_id": "test_public_client_id",
            "redirect_uri": "https://example.com/callback",
            "response_type": "code",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "allow": True,
            "access_level": OAuthApplicationAccessLevel.ALL.value,
            "scoped_organizations": [],
            "scoped_teams": [],
            "scope": "openid",
        }

        response = self.client.post("/oauth/authorize/", public_auth_data)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        # Try to exchange code without code_verifier
        token_response = self.post(
            "/oauth/token/",
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": "test_public_client_id",
                "redirect_uri": "https://example.com/callback",
            },
        )

        assert token_response.status_code == status.HTTP_400_BAD_REQUEST
        assert token_response.json()["error"] == "invalid_request"

    def test_public_client_userinfo_access(self):
        # Complete OAuth flow and get access token
        public_auth_data = {
            "client_id": "test_public_client_id",
            "redirect_uri": "https://example.com/callback",
            "response_type": "code",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "allow": True,
            "access_level": OAuthApplicationAccessLevel.ALL.value,
            "scoped_organizations": [],
            "scoped_teams": [],
            "scope": "openid profile email",
        }

        response = self.client.post("/oauth/authorize/", public_auth_data)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post(
            "/oauth/token/",
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": "test_public_client_id",
                "redirect_uri": "https://example.com/callback",
                "code_verifier": self.code_verifier,
            },
        )

        access_token = token_response.json()["access_token"]

        # Use access token to access userinfo endpoint
        userinfo_response = self.client.get("/oauth/userinfo/", headers={"Authorization": f"Bearer {access_token}"})

        assert userinfo_response.status_code == status.HTTP_200_OK
        userinfo_data = userinfo_response.json()

        # Verify expected user claims
        assert userinfo_data["sub"] == str(self.user.uuid)
        assert userinfo_data["email"] == self.user.email

    def test_public_client_scoped_access(self):
        # Test public client with team-scoped access
        scoped_auth_data = {
            "client_id": "test_public_client_id",
            "redirect_uri": "https://example.com/callback",
            "response_type": "code",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "allow": True,
            "access_level": OAuthApplicationAccessLevel.TEAM.value,
            "scoped_organizations": [],
            "scoped_teams": [self.team.id],
            "scope": "openid",
        }

        response = self.client.post("/oauth/authorize/", scoped_auth_data)
        assert response.status_code == status.HTTP_200_OK

        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post(
            "/oauth/token/",
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": "test_public_client_id",
                "redirect_uri": "https://example.com/callback",
                "code_verifier": self.code_verifier,
            },
        )

        assert token_response.status_code == status.HTTP_200_OK

        # Verify scoped access is preserved in token
        access_token = token_response.json()["access_token"]
        from posthog.models.oauth import OAuthAccessToken

        db_token = OAuthAccessToken.objects.get(token=access_token)
        assert db_token.scoped_teams == [self.team.id]

    def test_redirect_uri_exact_match_required_authorization(self):
        malicious_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback/malicious&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(malicious_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_request"
        assert response.json()["error_description"] == "Mismatching redirect URI."

    def test_redirect_uri_subdomain_attack_prevention(self):
        subdomain_attack_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://evil.example.com/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(subdomain_attack_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_request"
        assert response.json()["error_description"] == "Mismatching redirect URI."

    def test_redirect_uri_with_fragments_rejected(self):
        fragment_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback%23fragment&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(fragment_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_request"

    def test_redirect_uri_case_sensitivity(self):
        case_different_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://EXAMPLE.COM/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(case_different_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_request"
        assert response.json()["error_description"] == "Mismatching redirect URI."

    def test_redirect_uri_path_traversal_attack_prevention(self):
        path_traversal_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback/../admin&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(path_traversal_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_request"
        assert response.json()["error_description"] == "Mismatching redirect URI."

    def test_redirect_uri_query_parameter_checks_value(self):
        OAuthApplication.objects.create(
            name="App with Query Params",
            client_id="test_query_params_client",
            client_secret="test_query_params_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback?foo=bar",
            user=self.user,
            hash_client_secret=True,
            algorithm="RS256",
        )

        # Should work because it matches exactly
        redirect_uri = "https://example.com/callback?foo=bar"
        exact_match_url = f"/oauth/authorize/?client_id=test_query_params_client&redirect_uri={quote(redirect_uri)}&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(exact_match_url)
        assert response.status_code == status.HTTP_200_OK

        # Should fail because it has a different query parameter value for session
        different_param_redirect_uri = "https://example.com/callback?foo=baz"
        different_query_param_url = f"/oauth/authorize/?client_id=test_query_params_client&redirect_uri={quote(different_param_redirect_uri)}&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(different_query_param_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_request"
        assert response.json()["error_description"] == "Mismatching redirect URI."

    def test_redirect_uri_port_manipulation_attack(self):
        # Test that port manipulation is prevented
        port_attack_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com:8080/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(port_attack_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_request"
        assert response.json()["error_description"] == "Mismatching redirect URI."

    def test_redirect_uri_consistency_authorization_to_token(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_data = {
            **self.base_token_body,
            "code": code,
            "redirect_uri": "https://different.com/callback",  # Different from authorization
        }

        token_response = self.post("/oauth/token/", token_data)
        assert token_response.status_code == status.HTTP_400_BAD_REQUEST
        assert token_response.json()["error"] == "invalid_request"

    def test_state_parameter_csrf_protection(self):
        state_value = "secure_random_state_12345"

        auth_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256&state={state_value}"

        response = self.client.get(auth_url)
        assert response.status_code == status.HTTP_200_OK

        auth_data = {
            **self.base_authorization_post_body,
            "state": state_value,
        }

        response = self.client.post("/oauth/authorize/", auth_data)
        assert response.status_code == status.HTTP_200_OK

        redirect_to = response.json()["redirect_to"]
        assert f"state={state_value}" in redirect_to

        assert "code=" in redirect_to

    def test_state_parameter_preserved_in_error_responses(self):
        state_value = "error_state_preservation_test"

        # Use invalid client_id to trigger error
        auth_url = f"/oauth/authorize/?client_id=invalid_client&redirect_uri=https://example.com/callback&response_type=code&state={state_value}"

        response = self.client.get(auth_url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_request"

    def test_state_parameter_with_special_characters(self):
        # Test that state parameter handles special characters properly
        state_value = "state_with_!@#$%^&*()_+-={}[]|\\:;\"'<>,.?/"

        auth_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256&state={state_value}"

        response = self.client.get(auth_url)
        assert response.status_code == status.HTTP_200_OK

        auth_data = {
            **self.base_authorization_post_body,
            "state": state_value,
        }

        response = self.client.post("/oauth/authorize/", auth_data)
        assert response.status_code == status.HTTP_200_OK

        redirect_to = response.json()["redirect_to"]
        # URL encoding might occur, so we check for the presence rather than exact match
        assert "state=" in redirect_to

    def test_missing_state_parameter_handling(self):
        auth_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(auth_url)
        assert response.status_code == status.HTTP_200_OK

        # Complete authorization without state
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        assert response.status_code == status.HTTP_200_OK

        redirect_to = response.json()["redirect_to"]
        assert "code=" in redirect_to
        assert "state=" not in redirect_to

    def test_state_parameter_reuse(self):
        state_value = "reusable_state_value"

        auth_data = {
            **self.base_authorization_post_body,
            "state": state_value,
        }

        response1 = self.client.post("/oauth/authorize/", auth_data)
        assert response1.status_code == status.HTTP_200_OK
        redirect_to1 = response1.json()["redirect_to"]
        assert f"state={state_value}" in redirect_to1

        response2 = self.client.post("/oauth/authorize/", auth_data)
        assert response2.status_code == status.HTTP_200_OK
        redirect_to2 = response2.json()["redirect_to"]
        assert f"state={state_value}" in redirect_to2

    def test_state_parameter_length_limits(self):
        state_value = "a" * 2048

        auth_data = {
            **self.base_authorization_post_body,
            "state": state_value,
        }

        response = self.client.post("/oauth/authorize/", auth_data)
        assert response.status_code == status.HTTP_200_OK

        redirect_to = response.json()["redirect_to"]
        assert "state=" in redirect_to

    def test_denial_preserves_state_parameter(self):
        state_value = "denial_test_state"

        auth_data = {
            **self.base_authorization_post_body,
            "allow": False,
            "state": state_value,
        }

        response = self.client.post("/oauth/authorize/", auth_data)
        assert response.status_code == status.HTTP_200_OK

        redirect_to = response.json()["redirect_to"]
        assert "error=access_denied" in redirect_to
        assert f"state={state_value}" in redirect_to

    def test_nonce_uniqueness_validation(self):
        nonce_value = "test_nonce_12345"

        auth_data_with_nonce = {**self.base_authorization_post_body, "nonce": nonce_value, "scope": "openid"}

        response1 = self.client.post("/oauth/authorize/", auth_data_with_nonce)
        assert response1.status_code == status.HTTP_200_OK

        code1 = response1.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response1 = self.post("/oauth/token/", {**self.base_token_body, "code": code1})
        assert token_response1.status_code == status.HTTP_200_OK

        response2 = self.client.post("/oauth/authorize/", auth_data_with_nonce)
        assert response2.status_code == status.HTTP_200_OK

        code2 = response2.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response2 = self.post("/oauth/token/", {**self.base_token_body, "code": code2})
        assert token_response2.status_code == status.HTTP_200_OK

    def test_access_token_isolation_between_applications(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post("/oauth/token/", {**self.base_token_body, "code": code})
        access_token = token_response.json()["access_token"]

        other_app = OAuthApplication.objects.create(
            name="Other Test App",
            client_id="other_test_client_id",
            client_secret="other_test_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://other.com/callback",
            user=self.user,
            hash_client_secret=True,
            algorithm="RS256",
        )

        db_token = OAuthAccessToken.objects.get(token=access_token)
        assert db_token.application == self.confidential_application
        assert db_token.application != other_app

    def test_token_leakage_in_error_responses(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post("/oauth/token/", {**self.base_token_body, "code": code})
        access_token = token_response.json()["access_token"]

        invalid_requests = [
            {"grant_type": "invalid_grant", "token": access_token},
            {"client_id": "invalid_client", "token": access_token},
        ]

        for invalid_request in invalid_requests:
            response = self.post("/oauth/token/", invalid_request)
            response_text = response.content.decode()
            assert access_token not in response_text

    @freeze_time("2025-01-01 00:00:00")
    def test_refresh_token_reuse_within_grace_period(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post("/oauth/token/", {**self.base_token_body, "code": code})
        old_refresh_token = token_response.json()["refresh_token"]

        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": old_refresh_token,
            "client_id": self.confidential_application.client_id,
            "client_secret": "test_confidential_client_secret",
        }

        first_refresh_response = self.post("/oauth/token/", refresh_data)
        assert first_refresh_response.status_code == status.HTTP_200_OK
        new_refresh_token = first_refresh_response.json()["refresh_token"]
        new_access_token = first_refresh_response.json()["access_token"]

        # Reuse old refresh token within grace period (2 minutes by default)
        with freeze_time("2025-01-01 00:01:00"):
            reuse_response = self.post("/oauth/token/", refresh_data)
            assert reuse_response.status_code == status.HTTP_200_OK

            assert reuse_response.json()["refresh_token"] == new_refresh_token
            assert reuse_response.json()["access_token"] == new_access_token

    @freeze_time("2025-01-01 00:00:00")
    def test_refresh_token_reuse_after_grace_period_revokes_token_family(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post("/oauth/token/", {**self.base_token_body, "code": code})
        old_refresh_token = token_response.json()["refresh_token"]

        # Use refresh token for the first time
        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": old_refresh_token,
            "client_id": self.confidential_application.client_id,
            "client_secret": "test_confidential_client_secret",
        }

        first_refresh_response = self.post("/oauth/token/", refresh_data)
        assert first_refresh_response.status_code == status.HTTP_200_OK
        new_refresh_token = first_refresh_response.json()["refresh_token"]

        # Try to reuse old refresh token after grace period (2 minutes by default)
        with freeze_time("2025-01-01 00:03:00"):
            reuse_response = self.post("/oauth/token/", refresh_data)
            assert reuse_response.status_code == status.HTTP_400_BAD_REQUEST
            assert reuse_response.json()["error"] == "invalid_grant"

            # Verify all tokens in the family are revoked
            old_token_db = OAuthRefreshToken.objects.get(token=old_refresh_token)
            assert old_token_db.revoked is not None

            # New refresh token should also be revoked
            new_token_db = OAuthRefreshToken.objects.get(token=new_refresh_token)
            assert new_token_db.revoked is not None

            # The new refresh token behavior depends on the OAuth library implementation
            # Some implementations may immediately revoke all tokens in the family,
            # while others may only mark them as suspicious for future use

    @freeze_time("2025-01-01 00:00:00")
    def test_multiple_refresh_token_rotations_preserve_token_family(self):
        # Get initial tokens
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post("/oauth/token/", {**self.base_token_body, "code": code})
        initial_refresh_token = token_response.json()["refresh_token"]

        # Get the token family UUID from the initial refresh token
        initial_token_db = OAuthRefreshToken.objects.get(token=initial_refresh_token)
        token_family = initial_token_db.token_family

        refresh_tokens = [initial_refresh_token]

        # Perform multiple refresh token rotations
        for _ in range(5):
            refresh_data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_tokens[-1],
                "client_id": self.confidential_application.client_id,
                "client_secret": "test_confidential_client_secret",
            }

            refresh_response = self.post("/oauth/token/", refresh_data)
            assert refresh_response.status_code == status.HTTP_200_OK

            new_refresh_token = refresh_response.json()["refresh_token"]
            refresh_tokens.append(new_refresh_token)

            # Verify the new token has the same token family
            new_token_db = OAuthRefreshToken.objects.get(token=new_refresh_token)
            assert new_token_db.token_family == token_family

    @freeze_time("2025-01-01 00:00:00")
    def test_concurrent_refresh_token_requests_within_grace_period(self):
        # Get initial tokens
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post("/oauth/token/", {**self.base_token_body, "code": code})
        old_refresh_token = token_response.json()["refresh_token"]

        # Use refresh token for the first time
        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": old_refresh_token,
            "client_id": self.confidential_application.client_id,
            "client_secret": "test_confidential_client_secret",
        }

        first_refresh_response = self.post("/oauth/token/", refresh_data)
        assert first_refresh_response.status_code == status.HTTP_200_OK
        first_new_tokens = first_refresh_response.json()

        # Simulate concurrent request with the same old refresh token within grace period
        with freeze_time("2025-01-01 00:00:30"):  # 30 seconds later
            concurrent_response = self.post("/oauth/token/", refresh_data)
            assert concurrent_response.status_code == status.HTTP_200_OK

            # Should return the same tokens as the first refresh
            assert concurrent_response.json()["refresh_token"] == first_new_tokens["refresh_token"]
            assert concurrent_response.json()["access_token"] == first_new_tokens["access_token"]

    @freeze_time("2025-01-01 00:00:00")
    def test_refresh_token_reuse_with_different_client_fails(self):
        # Get initial tokens for first application
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post("/oauth/token/", {**self.base_token_body, "code": code})
        refresh_token = token_response.json()["refresh_token"]

        # Try to use refresh token with a different client
        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.public_application.client_id,
            "client_secret": "test_public_client_secret",
        }

        response = self.post("/oauth/token/", refresh_data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "invalid_grant"

    def test_invalid_scope_validation_with_and_without_trailing_slash(self):
        """Test that invalid scope validation works with and without trailing slash."""

        # Test with trailing slash (this should work correctly - scope validation happens)
        invalid_scope_url_with_slash = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256&scope=invalid_scope_name"

        response = self.client.get(invalid_scope_url_with_slash)
        assert response.status_code == status.HTTP_302_FOUND
        location = response.get("Location")
        assert location
        assert "error=invalid_scope" in location

        # Test without trailing slash (should now also validate scopes after fix)
        invalid_scope_url_without_slash = f"/oauth/authorize?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256&scope=invalid_scope_name"

        response = self.client.get(invalid_scope_url_without_slash)

        # After the fix, both should behave the same - redirect with error
        assert response.status_code == status.HTTP_302_FOUND
        location = response.get("Location")
        assert location
        assert "error=invalid_scope" in location

    def test_token_endpoint_with_json_payload(self):
        grant = OAuthGrant.objects.create(
            application=self.confidential_application,
            user=self.user,
            code="test_json_code",
            code_challenge=self.code_challenge,
            code_challenge_method="S256",
            redirect_uri="https://example.com/callback",
            expires=timezone.now() + timedelta(minutes=5),
            scoped_organizations=[],
            scoped_teams=[],
        )

        token_data = {
            "grant_type": "authorization_code",
            "code": grant.code,
            "client_id": "test_confidential_client_id",
            "client_secret": "test_confidential_client_secret",
            "redirect_uri": "https://example.com/callback",
            "code_verifier": self.code_verifier,
        }

        response = self.client.post(
            "/oauth/token/",
            data=token_data,
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert "access_token" in response_data
        assert "refresh_token" in response_data
        assert "token_type" in response_data
        assert "scoped_teams" in response_data
        assert "scoped_organizations" in response_data
        assert response_data["token_type"] == "Bearer"
        assert response_data["scoped_teams"] == []
        assert response_data["scoped_organizations"] == []

    def test_token_endpoint_with_invalid_json_payload(self):
        response = self.client.post(
            "/oauth/token/",
            data="invalid json{{{",
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        response_data = response.json()
        assert response_data["error"] == "invalid_request"
        assert "Invalid JSON" in response_data["error_description"]

    def _create_access_and_refresh_tokens(self, scopes: str = "openid") -> tuple[OAuthAccessToken, OAuthRefreshToken]:
        response = self.client.post(
            "/oauth/authorize/",
            {**self.base_authorization_post_body, "scope": scopes},
        )
        assert response.status_code == status.HTTP_200_OK

        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        response = self.post("/oauth/token/", {**self.base_token_body, "code": code})
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        access_token = OAuthAccessToken.objects.get(token=data["access_token"])
        refresh_token = OAuthRefreshToken.objects.get(token=data["refresh_token"])

        return access_token, refresh_token

    @parameterized.expand([("access_token", True), ("refresh_token", False)])
    def test_introspection_with_http_basic_auth(self, token_type, expected_active):
        access_token, refresh_token = self._create_access_and_refresh_tokens()
        token = access_token if token_type == "access_token" else refresh_token

        authorization_header = self.get_basic_auth_header(
            "test_confidential_client_id", "test_confidential_client_secret"
        )

        response = self.post(
            "/oauth/introspect/",
            {"token": token.token},
            headers={"Authorization": authorization_header},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["active"] == expected_active

        if expected_active:
            assert data["scope"] == "openid"
            assert data["client_id"] == "test_confidential_client_id"
            assert "scoped_teams" in data
            assert "scoped_organizations" in data
            assert "exp" in data

    @parameterized.expand([("access_token", True), ("refresh_token", False)])
    def test_introspection_with_client_credentials_in_body(self, token_type, expected_active):
        access_token, refresh_token = self._create_access_and_refresh_tokens()
        token = access_token if token_type == "access_token" else refresh_token

        response = self.post(
            "/oauth/introspect/",
            {
                "token": token.token,
                "client_id": "test_confidential_client_id",
                "client_secret": "test_confidential_client_secret",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["active"] == expected_active

        if expected_active:
            assert data["scope"] == "openid"
            assert data["client_id"] == "test_confidential_client_id"

    def test_introspection_with_bearer_token_requires_introspection_scope(self):
        access_token, _ = self._create_access_and_refresh_tokens(scopes="openid")
        token_to_introspect, _ = self._create_access_and_refresh_tokens()

        response = self.post(
            "/oauth/introspect/",
            {"token": token_to_introspect.token},
            headers={"Authorization": f"Bearer {access_token.token}"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand([("access_token", True), ("refresh_token", False)])
    def test_introspection_with_bearer_token_with_introspection_scope(self, token_type, expected_active):
        access_token, _ = self._create_access_and_refresh_tokens(scopes="openid introspection")
        token_to_introspect_access, token_to_introspect_refresh = self._create_access_and_refresh_tokens()
        token_to_introspect = (
            token_to_introspect_access if token_type == "access_token" else token_to_introspect_refresh
        )

        response = self.post(
            "/oauth/introspect/",
            {"token": token_to_introspect.token},
            headers={"Authorization": f"Bearer {access_token.token}"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["active"] == expected_active

        if expected_active:
            assert data["scope"] == "openid"

    def test_introspection_with_invalid_token(self):
        authorization_header = self.get_basic_auth_header(
            "test_confidential_client_id", "test_confidential_client_secret"
        )

        response = self.post(
            "/oauth/introspect/",
            {"token": "invalid_token"},
            headers={"Authorization": authorization_header},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert not data["active"]
        assert len(data) == 1

    def test_introspection_without_authentication_fails(self):
        access_token, _ = self._create_access_and_refresh_tokens()

        response = self.post("/oauth/introspect/", {"token": access_token.token})

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_introspection_with_wrong_client_credentials_fails(self):
        access_token, _ = self._create_access_and_refresh_tokens()

        response = self.post(
            "/oauth/introspect/",
            {
                "token": access_token.token,
                "client_id": "test_confidential_client_id",
                "client_secret": "wrong_secret",
            },
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @freeze_time("2025-01-01 00:00:00")
    def test_introspection_with_expired_token(self):
        access_token, _ = self._create_access_and_refresh_tokens()

        access_token.expires = timezone.now() - timedelta(hours=1)
        access_token.save()

        authorization_header = self.get_basic_auth_header(
            "test_confidential_client_id", "test_confidential_client_secret"
        )

        response = self.post(
            "/oauth/introspect/",
            {"token": access_token.token},
            headers={"Authorization": authorization_header},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert not data["active"]

    def test_introspection_via_get_method(self):
        access_token, _ = self._create_access_and_refresh_tokens()

        authorization_header = self.get_basic_auth_header(
            "test_confidential_client_id", "test_confidential_client_secret"
        )

        response = self.client.get(
            f"/oauth/introspect/?token={access_token.token}",
            headers={"Authorization": authorization_header},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["active"]

    def test_introspection_with_json_body(self):
        access_token, _ = self._create_access_and_refresh_tokens()

        authorization_header = self.get_basic_auth_header(
            "test_confidential_client_id", "test_confidential_client_secret"
        )

        response = self.client.post(
            "/oauth/introspect/",
            {"token": access_token.token},
            content_type="application/json",
            headers={"Authorization": authorization_header},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["active"]
        assert data["scope"] == "openid"

    def test_introspection_with_missing_token_returns_inactive(self):
        authorization_header = self.get_basic_auth_header(
            "test_confidential_client_id", "test_confidential_client_secret"
        )

        response = self.post(
            "/oauth/introspect/",
            {},
            headers={"Authorization": authorization_header},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert not data["active"]
