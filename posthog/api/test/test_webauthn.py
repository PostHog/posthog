import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.api.webauthn import WEBAUTHN_REGISTRATION_CHALLENGE_KEY
from posthog.models import User
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.webauthn_credential import WebauthnCredential


class TestWebAuthnRegistration(APIBaseTest):
    """Tests for WebAuthn passkey registration flow."""

    def test_registration_begin_requires_authentication(self):
        self.client.logout()
        response = self.client.post("/api/webauthn/register/begin/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_registration_begin_returns_options(self):
        response = self.client.post("/api/webauthn/register/begin/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("rp", data)
        self.assertIn("user", data)
        self.assertIn("challenge", data)
        self.assertIn("pubKeyCredParams", data)
        self.assertIn("timeout", data)
        self.assertIn("authenticatorSelection", data)

        self.assertEqual(data["rp"]["name"], "PostHog")
        self.assertEqual(data["user"]["name"], self.user.email)
        self.assertEqual(data["authenticatorSelection"]["residentKey"], "required")

    def test_registration_begin_excludes_existing_credentials(self):
        WebauthnCredential.objects.create(
            user=self.user,
            credential_id=b"existing-credential-id",
            label="Existing Passkey",
            public_key=b"public-key",
            algorithm=-7,
            counter=0,
            transports=["internal"],
            verified=True,
        )

        response = self.client.post("/api/webauthn/register/begin/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["excludeCredentials"]), 1)

    def test_registration_begin_disallowed_when_sso_enforced(self):
        email_domain = self.user.email.split("@", 1)[1]

        self.organization.available_product_features = [
            {"key": "sso_enforcement", "name": "sso_enforcement"},
            {"key": "saml", "name": "saml"},
        ]
        self.organization.save()

        OrganizationDomain.objects.create(
            domain=email_domain,
            organization=self.organization,
            verified_at=timezone.now(),
            sso_enforcement="saml",
        )

        response = self.client.post("/api/webauthn/register/begin/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("requires SSO", response.json().get("detail", ""))

    def test_registration_complete_disallowed_when_sso_enforced(self):
        email_domain = self.user.email.split("@", 1)[1]

        self.organization.available_product_features = [
            {"key": "sso_enforcement", "name": "sso_enforcement"},
            {"key": "saml", "name": "saml"},
        ]
        self.organization.save()

        OrganizationDomain.objects.create(
            domain=email_domain,
            organization=self.organization,
            verified_at=timezone.now(),
            sso_enforcement="saml",
        )

        session = self.client.session
        session[WEBAUTHN_REGISTRATION_CHALLENGE_KEY] = "dummy"
        session.save()

        response = self.client.post("/api/webauthn/register/complete/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("requires SSO", response.json().get("detail", ""))

    def test_registration_complete_without_challenge_fails(self):
        response = self.client.post("/api/webauthn/register/complete/", {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.json())

    @patch("posthog.api.webauthn.decode_credential_public_key")
    @patch("posthog.api.webauthn.verify_registration_response")
    def test_registration_complete_stores_unverified_credential(self, mock_verify, mock_decode):
        begin_response = self.client.post("/api/webauthn/register/begin/")
        self.assertEqual(begin_response.status_code, status.HTTP_200_OK)

        mock_verify.return_value = MagicMock(
            credential_id=b"new-credential-id",
            credential_public_key=b"public-key-bytes",
            sign_count=0,
        )
        mock_decode.return_value = MagicMock(alg=-7)

        complete_response = self.client.post(
            "/api/webauthn/register/complete/",
            {
                "id": "base64url-encoded-id",
                "rawId": "base64url-encoded-raw-id",
                "type": "public-key",
                "response": {
                    "attestationObject": "base64url-encoded",
                    "clientDataJSON": "base64url-encoded",
                    "transports": ["internal", "hybrid"],
                },
                "label": "My New Passkey",
            },
            format="json",
        )
        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)

        data = complete_response.json()
        self.assertTrue(data["success"])
        self.assertIn("credential_id", data)

        credential = WebauthnCredential.objects.get(pk=data["credential_id"])
        self.assertEqual(credential.user, self.user)
        self.assertEqual(credential.label, "My New Passkey")
        self.assertFalse(credential.verified)


class TestWebAuthnLogin(APIBaseTest):
    """Tests for WebAuthn passkey login flow."""

    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        super().setUp()
        self.credential = WebauthnCredential.objects.create(
            user=self.user,
            credential_id=b"test-credential-id",
            label="Test Passkey",
            public_key=b"test-public-key",
            algorithm=-7,
            counter=0,
            transports=["internal"],
            verified=True,
        )

    def test_login_begin_returns_options(self):
        response = self.client.post("/api/webauthn/login/begin/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("challenge", data)
        self.assertIn("timeout", data)
        self.assertIn("rpId", data)
        self.assertEqual(data["allowCredentials"], [])
        self.assertEqual(data["userVerification"], "required")

    def test_login_complete_without_challenge_fails(self):
        response = self.client.post("/api/webauthn/login/complete/", {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_complete_without_user_handle_fails(self):
        self.client.post("/api/webauthn/login/begin/")

        response = self.client.post(
            "/api/webauthn/login/complete/",
            {
                "id": "some-id",
                "rawId": "some-raw-id",
                "type": "public-key",
                "response": {
                    "authenticatorData": "data",
                    "clientDataJSON": "data",
                    "signature": "sig",
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("userHandle", response.json()["error"])

    @patch("posthog.auth.verify_authentication_response")
    def test_login_complete_success(self, mock_verify):
        from webauthn.helpers import bytes_to_base64url

        from posthog.api.webauthn import user_uuid_to_handle

        self.client.post("/api/webauthn/login/begin/")

        mock_verify.return_value = MagicMock(new_sign_count=1)

        # user handle is the user.uuid encoded as bytes
        user_handle = user_uuid_to_handle(self.user.uuid)

        response = self.client.post(
            "/api/webauthn/login/complete/",
            {
                "id": bytes_to_base64url(self.credential.credential_id),
                "rawId": bytes_to_base64url(self.credential.credential_id),
                "type": "public-key",
                "response": {
                    "authenticatorData": "data",
                    "clientDataJSON": "data",
                    "signature": "sig",
                    "userHandle": bytes_to_base64url(user_handle),
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["success"])

        me_response = self.client.get("/api/users/@me/")
        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(me_response.json()["email"], self.user.email)

    @patch("posthog.auth.verify_authentication_response")
    def test_login_with_unverified_credential_fails(self, mock_verify):
        from webauthn.helpers import bytes_to_base64url

        from posthog.api.webauthn import user_uuid_to_handle

        self.credential.verified = False
        self.credential.save()

        self.client.post("/api/webauthn/login/begin/")

        user_handle = user_uuid_to_handle(self.user.uuid)

        response = self.client.post(
            "/api/webauthn/login/complete/",
            {
                "id": bytes_to_base64url(self.credential.credential_id),
                "rawId": bytes_to_base64url(self.credential.credential_id),
                "type": "public-key",
                "response": {
                    "authenticatorData": "data",
                    "clientDataJSON": "data",
                    "signature": "sig",
                    "userHandle": bytes_to_base64url(user_handle),
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("authentication failed", response.json()["error"].lower())


class TestWebAuthnCredentialManagement(APIBaseTest):
    """Tests for WebAuthn credential CRUD operations."""

    def setUp(self):
        super().setUp()
        self.credential = WebauthnCredential.objects.create(
            user=self.user,
            credential_id=b"test-credential-id",
            label="My Passkey",
            public_key=b"public-key",
            algorithm=-7,
            counter=0,
            transports=["internal"],
            verified=True,
        )

    def test_list_credentials_requires_auth(self):
        self.client.logout()
        response = self.client.get("/api/webauthn/credentials/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_credentials_returns_all(self):
        WebauthnCredential.objects.create(
            user=self.user,
            credential_id=b"unverified-credential",
            label="Unverified",
            public_key=b"public-key",
            algorithm=-7,
            counter=0,
            transports=[],
            verified=False,
        )

        response = self.client.get("/api/webauthn/credentials/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        credentials = response.json()
        self.assertEqual(len(credentials), 2)

    def test_list_credentials_only_returns_own(self):
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password123")
        WebauthnCredential.objects.create(
            user=other_user,
            credential_id=b"other-credential",
            label="Other User Passkey",
            public_key=b"public-key",
            algorithm=-7,
            counter=0,
            transports=[],
            verified=True,
        )

        response = self.client.get("/api/webauthn/credentials/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        credentials = response.json()
        self.assertEqual(len(credentials), 1)
        self.assertEqual(credentials[0]["label"], "My Passkey")

    def test_delete_credential(self):
        response = self.client.delete(f"/api/webauthn/credentials/{self.credential.pk}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(WebauthnCredential.objects.filter(pk=self.credential.pk).exists())

    def test_delete_nonexistent_credential(self):
        response = self.client.delete(f"/api/webauthn/credentials/{uuid.uuid4()}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_other_users_credential_fails(self):
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password123")
        other_credential = WebauthnCredential.objects.create(
            user=other_user,
            credential_id=b"other-credential",
            label="Other Passkey",
            public_key=b"public-key",
            algorithm=-7,
            counter=0,
            transports=[],
            verified=True,
        )

        response = self.client.delete(f"/api/webauthn/credentials/{other_credential.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_rename_credential(self):
        response = self.client.patch(
            f"/api/webauthn/credentials/{self.credential.pk}/",
            {"label": "Renamed Passkey"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["label"], "Renamed Passkey")

        self.credential.refresh_from_db()
        self.assertEqual(self.credential.label, "Renamed Passkey")

    @parameterized.expand(
        [
            ("empty", "", "Label is required"),
            ("too_long", "x" * 201, "200 characters"),
        ]
    )
    def test_rename_with_invalid_label(self, name, label, expected_error):
        response = self.client.patch(
            f"/api/webauthn/credentials/{self.credential.pk}/",
            {"label": label},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(expected_error, response.json()["error"])
