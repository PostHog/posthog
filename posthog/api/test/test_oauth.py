import base64
from datetime import timedelta
import hashlib
from typing import Optional
from django.test import override_settings
from freezegun import freeze_time
import jwt
from rest_framework import status
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
        return settings.OAUTH2_PROVIDER["OIDC_RSA_PRIVATE_KEY"]

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

        expiration_minutes = settings.OAUTH2_PROVIDER["AUTHORIZATION_CODE_EXPIRE_SECONDS"] / 60
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
        response = self.client.get("/oauth/.well-known/jwks.json")
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

        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        public_key_pem = public_key_pem.decode("utf-8")

        self.assertEqual(public_key_pem, self.public_key)

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
            "access_level": OAuthApplicationAccessLevel.ALL.value,
        }

        with self.assertRaises(ValueError) as cm:
            OAuthAuthorizationSerializer(data=data)
        self.assertEqual(str(cm.exception), "OAuthAuthorizationSerializer requires 'user' in context")

        with self.assertRaises(ValueError) as cm:
            OAuthAuthorizationSerializer(data=data, context={})
        self.assertEqual(str(cm.exception), "OAuthAuthorizationSerializer requires 'user' in context")

        serializer = OAuthAuthorizationSerializer(data=data, context={"user": self.user})
        self.assertTrue(serializer.is_valid())
