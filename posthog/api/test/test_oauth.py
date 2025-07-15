import base64
from datetime import timedelta
import hashlib
from typing import Optional, cast
from django.test import override_settings
from freezegun import freeze_time
import jwt
from rest_framework import status
from posthog.models.team.team import Team
from posthog.test.base import APIBaseTest
from posthog.models.oauth import (
    OAuthAccessToken,
    OAuthApplication,
    OAuthApplicationAccessLevel,
    OAuthGrant,
    OAuthRefreshToken,
)
from django.utils import timezone
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from django.conf import settings
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from posthog.api.oauth import OAuthAuthorizationSerializer
from urllib.parse import quote


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
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn(f"/login?next=/oauth/authorize/", response["Location"])

    def test_authorize_successful_with_required_params(self):
        response = self.client.get(self.base_authorization_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_authorize_missing_client_id(self):
        url = self.base_authorization_url

        url_without_client_id = self.replace_param_in_url(url, "client_id", None)

        response = self.client.get(url_without_client_id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")
        self.assertEqual(response.json()["error_description"], "Missing client_id parameter.")

    def test_authorize_invalid_client_id(self):
        url = self.base_authorization_url

        url_without_client_id = self.replace_param_in_url(url, "client_id", "invalid_id")

        response = self.client.get(url_without_client_id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")
        self.assertEqual(response.json()["error_description"], "Invalid client_id parameter value.")

    def test_authorize_missing_redirect_uri(self):
        # According to the spec, if the client has a single redirect URI, the authorization server does not require an
        # explicit redirect_uri parameter and can use the one provided by the application.
        url = self.base_authorization_url

        url_without_redirect_uri = self.replace_param_in_url(url, "redirect_uri", None)

        response = self.client.get(url_without_redirect_uri)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

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

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")
        self.assertEqual(response.json()["error_description"], "Missing redirect URI.")

    def test_authorize_invalid_redirect_uri(self):
        url = self.base_authorization_url

        url_without_redirect_uri = self.replace_param_in_url(url, "redirect_uri", "http://invalid.com/callback")

        response = self.client.get(url_without_redirect_uri)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")
        self.assertEqual(response.json()["error_description"], "Mismatching redirect URI.")

    def test_authorize_fails_without_pkce(self):
        url = self.base_authorization_url

        url_without_code_challenge = self.replace_param_in_url(url, "code_challenge", None)

        response = self.client.get(url_without_code_challenge)

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        location = response["Location"]

        self.assertIn("error=invalid_request", location)
        self.assertIn("error_description=Code+challenge+required", location)

    def test_authorize_post_fails_if_not_authenticated(self):
        self.client.logout()

        response = self.post(
            "/oauth/authorize/",
            self.base_authorization_post_body,
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @freeze_time("2025-01-01 00:00:00")
    def test_authorize_post_authorization_granted(self):
        response = self.client.post(
            "/oauth/authorize/",
            self.base_authorization_post_body,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        redirect_to = response.json()["redirect_to"]
        self.assertIn("code=", redirect_to)

        code = redirect_to.split("code=")[1].split("&")[0]

        grant = OAuthGrant.objects.get(code=code)

        self.assertEqual(grant.application, self.confidential_application)
        self.assertEqual(grant.user, self.user)
        self.assertEqual(grant.code, code)
        self.assertEqual(grant.code_challenge, self.code_challenge)
        self.assertEqual(grant.code_challenge_method, "S256")

        expiration_seconds = cast(int, settings.OAUTH2_PROVIDER["AUTHORIZATION_CODE_EXPIRE_SECONDS"])
        expiration_minutes = expiration_seconds / 60
        expected_expiration = timezone.now() + timedelta(minutes=expiration_minutes)
        self.assertEqual(grant.expires, expected_expiration)

    def test_authorize_post_denied_authorization(self):
        response = self.client.post(
            "/oauth/authorize/",
            {
                **self.base_authorization_post_body,
                "allow": False,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        redirect_to = response.json()["redirect_to"]
        self.assertEqual(redirect_to, "https://example.com/callback?error=access_denied")

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
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_grant")

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

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_token_endpoint_missing_grant_type(self):
        response = self.post("/oauth/token/", {})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "unsupported_grant_type")

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
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_full_oauth_flow(self):
        # 1. Get authorization request
        response = self.client.get(self.base_authorization_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # 2. Post authorization approval
        response = self.client.post(
            "/oauth/authorize/",
            self.base_authorization_post_body,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Extract authorization code from redirect URL
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        data = {
            **self.base_token_body,
            "code": code,
        }

        response = self.post("/oauth/token/", data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertIn("access_token", data)
        self.assertIn("token_type", data)
        self.assertIn("expires_in", data)
        self.assertIn("refresh_token", data)
        self.assertIn("scope", data)

        access_token = data["access_token"]
        refresh_token = data["refresh_token"]

        data = {"grant_type": "refresh_token", "refresh_token": refresh_token}

        authorization_header = self.get_basic_auth_header(
            "test_confidential_client_id", "test_confidential_client_secret"
        )

        response = self.post("/oauth/token/", data, headers={"Authorization": authorization_header})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)

        self.assertNotEqual(data["access_token"], access_token)
        self.assertNotEqual(data["refresh_token"], refresh_token)

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
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_scoped_organizations_with_all_access_level(self):
        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.ALL.value,
            "scoped_organizations": ["org1"],
            "scoped_teams": [1],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})

        self.assertFalse(serializer.is_valid())
        self.assertIn("scoped_organizations", serializer.errors)
        self.assertEqual(
            serializer.errors["scoped_organizations"][0], "scoped_organizations is not allowed when access_level is all"
        )

    def test_invalid_scoped_teams_with_organization_access_level(self):
        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.ORGANIZATION.value,
            "scoped_organizations": ["org1"],
            "scoped_teams": [1],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})
        self.assertFalse(serializer.is_valid())
        self.assertIn("scoped_teams", serializer.errors)
        self.assertEqual(
            serializer.errors["scoped_teams"][0], "scoped_teams is not allowed when access_level is organization"
        )

    def test_missing_scoped_organizations_with_organization_access_level(self):
        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.ORGANIZATION.value,
            "scoped_organizations": [],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})
        self.assertFalse(serializer.is_valid())
        self.assertIn("scoped_organizations", serializer.errors)
        self.assertEqual(
            serializer.errors["scoped_organizations"][0],
            "scoped_organizations is required when access_level is organization",
        )

    def test_missing_scoped_teams_with_team_access_level(self):
        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.TEAM.value,
            "scoped_teams": [],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})
        self.assertFalse(serializer.is_valid())
        self.assertIn("scoped_teams", serializer.errors)
        self.assertEqual(serializer.errors["scoped_teams"][0], "scoped_teams is required when access_level is team")

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

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        redirect_to = response.json()["redirect_to"]
        self.assertIn("code=", redirect_to)
        code = redirect_to.split("code=")[1].split("&")[0]

        self.assertIsNotNone(code)

        grant = OAuthGrant.objects.get(code=code)

        self.assertEqual(grant.scoped_teams, scoped_teams)

        token_data = {
            **self.base_token_body,
            "code": code,
        }

        token_response = self.post(
            "/oauth/token/",
            token_data,
        )

        self.assertEqual(token_response.status_code, status.HTTP_200_OK)
        token_response_data = token_response.json()

        self.assertIn("access_token", token_response_data)
        self.assertIn("refresh_token", token_response_data)

        access_token = OAuthAccessToken.objects.get(token=token_response_data["access_token"])

        self.assertEqual(access_token.scoped_teams, scoped_teams)

        refresh_token = OAuthRefreshToken.objects.get(token=token_response_data["refresh_token"])

        self.assertEqual(refresh_token.scoped_teams, scoped_teams)

        # refresh the access token
        refresh_token_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.confidential_application.client_id,
            "client_secret": "test_confidential_client_secret",
        }

        refresh_token_response = self.post("/oauth/token/", refresh_token_data)

        self.assertEqual(refresh_token_response.status_code, status.HTTP_200_OK)
        refresh_token_response_data = refresh_token_response.json()

        self.assertIn("access_token", refresh_token_response_data)
        self.assertIn("refresh_token", refresh_token_response_data)

        access_token = OAuthAccessToken.objects.get(token=refresh_token_response_data["access_token"])

        self.assertEqual(access_token.scoped_teams, scoped_teams)

        refresh_token = OAuthRefreshToken.objects.get(token=refresh_token_response_data["refresh_token"])

        self.assertEqual(refresh_token.scoped_teams, scoped_teams)

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

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        redirect_to = response.json()["redirect_to"]
        self.assertIn("code=", redirect_to)
        code = redirect_to.split("code=")[1].split("&")[0]

        self.assertIsNotNone(code)

        grant = OAuthGrant.objects.get(code=code)

        self.assertEqual(grant.scoped_organizations, scoped_organizations)

        token_data = {
            **self.base_token_body,
            "code": code,
        }

        token_response = self.post(
            "/oauth/token/",
            token_data,
        )

        self.assertEqual(token_response.status_code, status.HTTP_200_OK)
        token_response_data = token_response.json()

        access_token = OAuthAccessToken.objects.get(token=token_response_data["access_token"])

        self.assertEqual(access_token.scoped_organizations, scoped_organizations)

        refresh_token = OAuthRefreshToken.objects.get(token=token_response_data["refresh_token"])

        self.assertEqual(refresh_token.scoped_organizations, scoped_organizations)

        refresh_token_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.confidential_application.client_id,
            "client_secret": "test_confidential_client_secret",
        }

        refresh_token_response = self.post("/oauth/token/", refresh_token_data)

        self.assertEqual(refresh_token_response.status_code, status.HTTP_200_OK)
        refresh_token_response_data = refresh_token_response.json()

        self.assertIn("access_token", refresh_token_response_data)
        self.assertIn("refresh_token", refresh_token_response_data)

        access_token = OAuthAccessToken.objects.get(token=refresh_token_response_data["access_token"])

        self.assertEqual(access_token.scoped_organizations, scoped_organizations)

        refresh_token = OAuthRefreshToken.objects.get(token=refresh_token_response_data["refresh_token"])

        self.assertEqual(refresh_token.scoped_organizations, scoped_organizations)

    # OIDC tests

    def test_full_oidc_flow(self):
        data_with_openid = {
            **self.base_authorization_post_body,
            "scope": "openid email profile experiment:read",
        }

        response = self.client.post("/oauth/authorize/", data_with_openid)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        redirect_to = response.json().get("redirect_to", "")
        self.assertIn("code=", redirect_to)

        code = redirect_to.split("code=")[1].split("&")[0]

        token_data = {
            **self.base_token_body,
            "code": code,
        }

        token_response = self.post("/oauth/token/", token_data)

        self.assertEqual(token_response.status_code, status.HTTP_200_OK)
        token_response_data = token_response.json()

        self.assertIn("id_token", token_response_data)

        id_token = token_response_data["id_token"]

        decoded_token = jwt.decode(
            id_token, self.public_key, algorithms=["RS256"], audience=self.confidential_application.client_id
        )

        # Verify the claims
        self.assertEqual(decoded_token["sub"], str(self.user.uuid))
        self.assertEqual(decoded_token["email"], self.user.email)
        self.assertEqual(decoded_token["email_verified"], self.user.is_email_verified or False)
        self.assertEqual(decoded_token["given_name"], self.user.first_name)
        self.assertEqual(decoded_token["family_name"], self.user.last_name)

        # Fetch /oauth/userinfo
        userinfo_response = self.client.get(
            "/oauth/userinfo/", headers={"Authorization": f"Bearer {token_response_data['access_token']}"}
        )
        self.assertEqual(userinfo_response.status_code, status.HTTP_200_OK)
        userinfo_data = userinfo_response.json()

        # Verify the response matches the decoded token
        self.assertEqual(userinfo_data["sub"], str(self.user.uuid))
        self.assertEqual(userinfo_data["email"], self.user.email)
        self.assertEqual(userinfo_data["email_verified"], self.user.is_email_verified or False)
        self.assertEqual(userinfo_data["given_name"], self.user.first_name)
        self.assertEqual(userinfo_data["family_name"], self.user.last_name)

    def test_jwks_endpoint_returns_valid_jwks(self):
        response = self.client.get("/.well-known/jwks.json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        jwks = response.json()
        self.assertIn("keys", jwks)

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

        self.assertEqual(public_key_pem_str, self.public_key)

    def test_id_token_not_returned_without_openid_scope(self):
        data_without_openid = {
            **self.base_authorization_post_body,
            "scope": "experiment:read action:write",
        }

        response = self.client.post("/oauth/authorize/", data_without_openid)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        redirect_to = response.json().get("redirect_to", "")
        self.assertIn("code=", redirect_to)

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

        self.assertEqual(token_response.status_code, status.HTTP_200_OK)
        token_response_data = token_response.json()

        self.assertIn("access_token", token_response_data)
        self.assertIn("refresh_token", token_response_data)

        self.assertNotIn("id_token", token_response_data)

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

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        refresh_token.refresh_from_db()

        self.assertEqual(refresh_token.revoked, timezone.now())

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

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        refresh_token.refresh_from_db()

        self.assertIsNone(refresh_token.revoked)

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

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        refresh_token.refresh_from_db()

        self.assertEqual(refresh_token.revoked, timezone.now())

    def test_serializer_requires_user_in_context(self):
        data = {
            **self.base_authorization_post_body,
        }

        with self.assertRaises(ValueError) as cm:
            OAuthAuthorizationSerializer(data=data)
        self.assertEqual(str(cm.exception), "OAuthAuthorizationSerializer requires 'user' in context")

        with self.assertRaises(ValueError) as cm:
            OAuthAuthorizationSerializer(data=data, context={})
        self.assertEqual(str(cm.exception), "OAuthAuthorizationSerializer requires 'user' in context")

        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})
        self.assertTrue(serializer.is_valid())

    def test_cannot_scope_to_unauthorized_organization(self):
        from posthog.models import Organization

        other_org = Organization.objects.create(name="Other Organization")

        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.ORGANIZATION.value,
            "scoped_organizations": [str(other_org.id)],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})

        self.assertFalse(serializer.is_valid())
        self.assertIn("scoped_organizations", serializer.errors)
        self.assertIn(
            f"You must be a member of organization '{other_org.id}'", str(serializer.errors["scoped_organizations"][0])
        )

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

        self.assertFalse(serializer.is_valid())
        self.assertIn("scoped_teams", serializer.errors)
        self.assertIn(f"You must be a member of team '{other_team.id}'", str(serializer.errors["scoped_teams"][0]))

    def test_malformed_organization_uuid_rejected(self):
        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.ORGANIZATION.value,
            "scoped_organizations": ["invalid-uuid", "not-a-uuid-at-all"],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})

        self.assertFalse(serializer.is_valid())
        self.assertIn("scoped_organizations", serializer.errors)
        self.assertIn("Invalid organization UUID", str(serializer.errors["scoped_organizations"][0]))

    def test_nonexistent_team_rejected(self):
        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.TEAM.value,
            "scoped_teams": [99999, 88888],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})

        self.assertFalse(serializer.is_valid())
        self.assertIn("scoped_teams", serializer.errors)
        self.assertIn("do not exist", str(serializer.errors["scoped_teams"][0]))

    def test_authorization_code_reuse_prevented(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]
        token_data = {**self.base_token_body, "code": code}

        response1 = self.post("/oauth/token/", token_data)
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        response2 = self.post("/oauth/token/", token_data)
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response2.json()["error"], "invalid_grant")

    def test_pkce_code_verifier_validation(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_data = {**self.base_token_body, "code": code, "code_verifier": "wrong_verifier"}

        response = self.post("/oauth/token/", token_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_redirect_uri_exact_match_required(self):
        malicious_data = {**self.base_authorization_post_body, "redirect_uri": "https://example.com/callback/malicious"}

        response = self.client.post("/oauth/authorize/", malicious_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

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
            self.assertEqual(refresh_response.status_code, status.HTTP_200_OK)

            new_access_token = refresh_response.json()["access_token"]
            db_token = OAuthAccessToken.objects.get(token=new_access_token)
            self.assertEqual(db_token.scoped_teams, [self.team.id])

            refresh_token = refresh_response.json()["refresh_token"]

    def test_revoked_refresh_token_invalidates_access_tokens(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post("/oauth/token/", {**self.base_token_body, "code": code})
        access_token = token_response.json()["access_token"]
        refresh_token = token_response.json()["refresh_token"]

        userinfo_response = self.client.get("/oauth/userinfo/", headers={"Authorization": f"Bearer {access_token}"})
        self.assertEqual(userinfo_response.status_code, status.HTTP_200_OK)

        revoke_data = {
            "token": refresh_token,
            "token_type_hint": "refresh_token",
            "client_id": self.confidential_application.client_id,
            "client_secret": "test_confidential_client_secret",
        }

        revoke_response = self.post("/oauth/revoke/", revoke_data)
        self.assertEqual(revoke_response.status_code, status.HTTP_200_OK)

        db_refresh_token = OAuthRefreshToken.objects.get(token=refresh_token)
        self.assertIsNotNone(db_refresh_token.revoked)

        userinfo_response_after_revoke = self.client.get(
            "/oauth/userinfo/", headers={"Authorization": f"Bearer {access_token}"}
        )
        self.assertEqual(userinfo_response_after_revoke.status_code, status.HTTP_401_UNAUTHORIZED)

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
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_wrong_client_credentials_rejected(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_data_wrong_secret = {
            **self.base_token_body,
            "code": code,
            "client_secret": "wrong_secret",
        }

        response = self.post("/oauth/token/", token_data_wrong_secret)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

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
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_grant")

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
        self.assertEqual(refresh_response.status_code, status.HTTP_200_OK)
        new_refresh_token = refresh_response.json()["refresh_token"]

        self.assertNotEqual(old_refresh_token, new_refresh_token)

        # Within grace period, old token should still work and return the same new tokens
        retry_old_token_within_grace = self.post("/oauth/token/", refresh_data)
        self.assertEqual(retry_old_token_within_grace.status_code, status.HTTP_200_OK)
        self.assertEqual(retry_old_token_within_grace.json()["refresh_token"], new_refresh_token)

        # After grace period, old token should be invalid
        with freeze_time("2025-01-01 00:03:00"):  # 3 minutes later, beyond grace period
            retry_old_token_after_grace = self.post("/oauth/token/", refresh_data)
            self.assertEqual(retry_old_token_after_grace.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(retry_old_token_after_grace.json()["error"], "invalid_grant")

    def test_mixed_scoped_access_levels_rejected(self):
        data = {
            **self.base_authorization_post_body,
            "access_level": OAuthApplicationAccessLevel.ORGANIZATION.value,
            "scoped_organizations": [str(self.organization.id)],
            "scoped_teams": [self.team.id],
        }
        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})

        self.assertFalse(serializer.is_valid())
        self.assertIn("scoped_teams", serializer.errors)

    def test_application_isolation_different_users(self):
        from posthog.models import User, Organization, OrganizationMembership

        other_org = Organization.objects.create(name="Other Org")
        other_user = User.objects.create_user(email="other@test.com", password="password", first_name="Other")
        OrganizationMembership.objects.create(user=other_user, organization=other_org)

        self.client.force_login(other_user)

        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]
        grant = OAuthGrant.objects.get(code=code)
        self.assertEqual(grant.user, other_user)
        self.assertNotEqual(grant.user, self.user)

    def test_authorization_code_expires_correctly(self):
        with freeze_time("2025-01-01 00:00:00") as frozen_time:
            response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
            code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

            frozen_time.tick(delta=timedelta(minutes=6))

            token_data = {**self.base_token_body, "code": code}
            response = self.post("/oauth/token/", token_data)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.json()["error"], "invalid_grant")

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        redirect_to = response.json()["redirect_to"]
        self.assertIn("error=invalid_request", redirect_to)

    def test_invalid_grant_type_rejected(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_data = {
            **self.base_token_body,
            "code": code,
            "grant_type": "password",
        }

        response = self.post("/oauth/token/", token_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")

    def test_userinfo_endpoint_requires_valid_token(self):
        response = self.client.get("/oauth/userinfo/", headers={"Authorization": "Bearer invalid_token"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_userinfo_endpoint_with_expired_token(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response = self.post("/oauth/token/", {**self.base_token_body, "code": code})
        access_token = token_response.json()["access_token"]

        db_token = OAuthAccessToken.objects.get(token=access_token)
        db_token.expires = timezone.now() - timedelta(hours=1)
        db_token.save()

        response = self.client.get("/oauth/userinfo/", headers={"Authorization": f"Bearer {access_token}"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_redirect_uri_with_query_params_handled_safely(self):
        auth_data = {
            **self.base_authorization_post_body,
            "redirect_uri": "https://example.com/callback?redirect=https://evil.com",
        }

        response = self.client.post("/oauth/authorize/", auth_data)

        response_data = response.json()
        redirect_to = response_data.get("redirect_to", "")

        self.assertTrue(redirect_to.startswith("https://example.com/callback"))
        self.assertNotIn("https://evil.com", redirect_to.split("?")[0])

    def test_authorization_code_cannot_be_used_across_different_applications(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

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
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_grant")

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        redirect_to = response.json()["redirect_to"]
        self.assertIn("error=invalid_request", redirect_to)
        self.assertIn("Code+challenge+required", redirect_to)

    def test_public_client_full_oauth_flow(self):
        # Public client authorization with PKCE
        public_auth_url = f"/oauth/authorize/?client_id=test_public_client_id&redirect_uri=https://example.com/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(public_auth_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)

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
        self.assertEqual(token_response.status_code, status.HTTP_200_OK)

        # Verify we get all expected tokens
        token_data = token_response.json()
        self.assertIn("access_token", token_data)
        self.assertIn("refresh_token", token_data)
        self.assertIn("token_type", token_data)
        self.assertIn("expires_in", token_data)

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
        self.assertEqual(refresh_response.status_code, status.HTTP_200_OK)

        refresh_response_data = refresh_response.json()
        self.assertIn("access_token", refresh_response_data)
        self.assertIn("refresh_token", refresh_response_data)

        # Verify token rotation occurred
        self.assertNotEqual(refresh_response_data["refresh_token"], refresh_token)

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
        self.assertEqual(token_response.status_code, status.HTTP_200_OK)

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

        self.assertEqual(token_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(token_response.json()["error"], "invalid_grant")

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

        self.assertEqual(token_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(token_response.json()["error"], "invalid_request")

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

        self.assertEqual(userinfo_response.status_code, status.HTTP_200_OK)
        userinfo_data = userinfo_response.json()

        # Verify expected user claims
        self.assertEqual(userinfo_data["sub"], str(self.user.uuid))
        self.assertEqual(userinfo_data["email"], self.user.email)

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)

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

        self.assertEqual(token_response.status_code, status.HTTP_200_OK)

        # Verify scoped access is preserved in token
        access_token = token_response.json()["access_token"]
        from posthog.models.oauth import OAuthAccessToken

        db_token = OAuthAccessToken.objects.get(token=access_token)
        self.assertEqual(db_token.scoped_teams, [self.team.id])

    def test_redirect_uri_exact_match_required_authorization(self):
        malicious_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback/malicious&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(malicious_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")
        self.assertEqual(response.json()["error_description"], "Mismatching redirect URI.")

    def test_redirect_uri_subdomain_attack_prevention(self):
        subdomain_attack_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://evil.example.com/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(subdomain_attack_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")
        self.assertEqual(response.json()["error_description"], "Mismatching redirect URI.")

    def test_redirect_uri_with_fragments_rejected(self):
        fragment_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback%23fragment&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(fragment_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")

    def test_redirect_uri_case_sensitivity(self):
        case_different_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://EXAMPLE.COM/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(case_different_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")
        self.assertEqual(response.json()["error_description"], "Mismatching redirect URI.")

    def test_redirect_uri_path_traversal_attack_prevention(self):
        path_traversal_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback/../admin&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(path_traversal_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")
        self.assertEqual(response.json()["error_description"], "Mismatching redirect URI.")

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
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should fail because it has a different query parameter value for session
        different_param_redirect_uri = "https://example.com/callback?foo=baz"
        different_query_param_url = f"/oauth/authorize/?client_id=test_query_params_client&redirect_uri={quote(different_param_redirect_uri)}&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(different_query_param_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")
        self.assertEqual(response.json()["error_description"], "Mismatching redirect URI.")

    def test_redirect_uri_port_manipulation_attack(self):
        # Test that port manipulation is prevented
        port_attack_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com:8080/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(port_attack_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")
        self.assertEqual(response.json()["error_description"], "Mismatching redirect URI.")

    def test_redirect_uri_consistency_authorization_to_token(self):
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        code = response.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_data = {
            **self.base_token_body,
            "code": code,
            "redirect_uri": "https://different.com/callback",  # Different from authorization
        }

        token_response = self.post("/oauth/token/", token_data)
        self.assertEqual(token_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(token_response.json()["error"], "invalid_request")

    def test_state_parameter_csrf_protection(self):
        state_value = "secure_random_state_12345"

        auth_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256&state={state_value}"

        response = self.client.get(auth_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        auth_data = {
            **self.base_authorization_post_body,
            "state": state_value,
        }

        response = self.client.post("/oauth/authorize/", auth_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        redirect_to = response.json()["redirect_to"]
        self.assertIn(f"state={state_value}", redirect_to)

        self.assertIn("code=", redirect_to)

    def test_state_parameter_preserved_in_error_responses(self):
        state_value = "error_state_preservation_test"

        # Use invalid client_id to trigger error
        auth_url = f"/oauth/authorize/?client_id=invalid_client&redirect_uri=https://example.com/callback&response_type=code&state={state_value}"

        response = self.client.get(auth_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_request")

    def test_state_parameter_with_special_characters(self):
        # Test that state parameter handles special characters properly
        state_value = "state_with_!@#$%^&*()_+-={}[]|\\:;\"'<>,.?/"

        auth_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256&state={state_value}"

        response = self.client.get(auth_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        auth_data = {
            **self.base_authorization_post_body,
            "state": state_value,
        }

        response = self.client.post("/oauth/authorize/", auth_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        redirect_to = response.json()["redirect_to"]
        # URL encoding might occur, so we check for the presence rather than exact match
        self.assertIn("state=", redirect_to)

    def test_missing_state_parameter_handling(self):
        auth_url = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256"

        response = self.client.get(auth_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Complete authorization without state
        response = self.client.post("/oauth/authorize/", self.base_authorization_post_body)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        redirect_to = response.json()["redirect_to"]
        self.assertIn("code=", redirect_to)
        self.assertNotIn("state=", redirect_to)

    def test_state_parameter_reuse(self):
        state_value = "reusable_state_value"

        auth_data = {
            **self.base_authorization_post_body,
            "state": state_value,
        }

        response1 = self.client.post("/oauth/authorize/", auth_data)
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        redirect_to1 = response1.json()["redirect_to"]
        self.assertIn(f"state={state_value}", redirect_to1)

        response2 = self.client.post("/oauth/authorize/", auth_data)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        redirect_to2 = response2.json()["redirect_to"]
        self.assertIn(f"state={state_value}", redirect_to2)

    def test_state_parameter_length_limits(self):
        state_value = "a" * 2048

        auth_data = {
            **self.base_authorization_post_body,
            "state": state_value,
        }

        response = self.client.post("/oauth/authorize/", auth_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        redirect_to = response.json()["redirect_to"]
        self.assertIn("state=", redirect_to)

    def test_denial_preserves_state_parameter(self):
        state_value = "denial_test_state"

        auth_data = {
            **self.base_authorization_post_body,
            "allow": False,
            "state": state_value,
        }

        response = self.client.post("/oauth/authorize/", auth_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        redirect_to = response.json()["redirect_to"]
        self.assertIn("error=access_denied", redirect_to)
        self.assertIn(f"state={state_value}", redirect_to)

    def test_nonce_uniqueness_validation(self):
        nonce_value = "test_nonce_12345"

        auth_data_with_nonce = {**self.base_authorization_post_body, "nonce": nonce_value, "scope": "openid"}

        response1 = self.client.post("/oauth/authorize/", auth_data_with_nonce)
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        code1 = response1.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response1 = self.post("/oauth/token/", {**self.base_token_body, "code": code1})
        self.assertEqual(token_response1.status_code, status.HTTP_200_OK)

        response2 = self.client.post("/oauth/authorize/", auth_data_with_nonce)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

        code2 = response2.json()["redirect_to"].split("code=")[1].split("&")[0]

        token_response2 = self.post("/oauth/token/", {**self.base_token_body, "code": code2})
        self.assertEqual(token_response2.status_code, status.HTTP_200_OK)

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
        self.assertEqual(db_token.application, self.confidential_application)
        self.assertNotEqual(db_token.application, other_app)

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
            self.assertNotIn(access_token, response_text)

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
        self.assertEqual(first_refresh_response.status_code, status.HTTP_200_OK)
        new_refresh_token = first_refresh_response.json()["refresh_token"]
        new_access_token = first_refresh_response.json()["access_token"]

        # Reuse old refresh token within grace period (2 minutes by default)
        with freeze_time("2025-01-01 00:01:00"):
            reuse_response = self.post("/oauth/token/", refresh_data)
            self.assertEqual(reuse_response.status_code, status.HTTP_200_OK)

            self.assertEqual(reuse_response.json()["refresh_token"], new_refresh_token)
            self.assertEqual(reuse_response.json()["access_token"], new_access_token)

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
        self.assertEqual(first_refresh_response.status_code, status.HTTP_200_OK)
        new_refresh_token = first_refresh_response.json()["refresh_token"]

        # Try to reuse old refresh token after grace period (2 minutes by default)
        with freeze_time("2025-01-01 00:03:00"):
            reuse_response = self.post("/oauth/token/", refresh_data)
            self.assertEqual(reuse_response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(reuse_response.json()["error"], "invalid_grant")

            # Verify all tokens in the family are revoked
            old_token_db = OAuthRefreshToken.objects.get(token=old_refresh_token)
            self.assertIsNotNone(old_token_db.revoked)

            # New refresh token should also be revoked
            new_token_db = OAuthRefreshToken.objects.get(token=new_refresh_token)
            self.assertIsNotNone(new_token_db.revoked)

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
            self.assertEqual(refresh_response.status_code, status.HTTP_200_OK)

            new_refresh_token = refresh_response.json()["refresh_token"]
            refresh_tokens.append(new_refresh_token)

            # Verify the new token has the same token family
            new_token_db = OAuthRefreshToken.objects.get(token=new_refresh_token)
            self.assertEqual(new_token_db.token_family, token_family)

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
        self.assertEqual(first_refresh_response.status_code, status.HTTP_200_OK)
        first_new_tokens = first_refresh_response.json()

        # Simulate concurrent request with the same old refresh token within grace period
        with freeze_time("2025-01-01 00:00:30"):  # 30 seconds later
            concurrent_response = self.post("/oauth/token/", refresh_data)
            self.assertEqual(concurrent_response.status_code, status.HTTP_200_OK)

            # Should return the same tokens as the first refresh
            self.assertEqual(concurrent_response.json()["refresh_token"], first_new_tokens["refresh_token"])
            self.assertEqual(concurrent_response.json()["access_token"], first_new_tokens["access_token"])

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
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_invalid_scope_validation_with_and_without_trailing_slash(self):
        """Test that invalid scope validation works with and without trailing slash."""

        # Test with trailing slash (this should work correctly - scope validation happens)
        invalid_scope_url_with_slash = f"/oauth/authorize/?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256&scope=invalid_scope_name"

        response = self.client.get(invalid_scope_url_with_slash)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        location = response.get("Location")
        assert location
        self.assertIn("error=invalid_scope", location)

        # Test without trailing slash (should now also validate scopes after fix)
        invalid_scope_url_without_slash = f"/oauth/authorize?client_id=test_confidential_client_id&redirect_uri=https://example.com/callback&response_type=code&code_challenge={self.code_challenge}&code_challenge_method=S256&scope=invalid_scope_name"

        response = self.client.get(invalid_scope_url_without_slash)

        # After the fix, both should behave the same - redirect with error
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        location = response.get("Location")
        assert location
        self.assertIn("error=invalid_scope", location)
