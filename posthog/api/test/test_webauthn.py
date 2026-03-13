import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.api.webauthn import WEBAUTHN_REGISTRATION_CHALLENGE_KEY, WebAuthnLoginViewSet
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
    @patch("posthog.api.webauthn.verify_passkey_registration_response")
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

    @patch("posthog.auth.verify_passkey_authentication_response")
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

    @patch("posthog.auth.verify_passkey_authentication_response")
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

    @patch("posthog.auth.verify_passkey_authentication_response")
    def test_login_rejects_spoofed_user_handle(self, mock_verify):
        """Spoofed userHandle pointing to a different user must be rejected."""
        from webauthn.helpers import bytes_to_base64url

        from posthog.api.webauthn import user_uuid_to_handle

        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password123")

        self.client.post("/api/webauthn/login/begin/")
        mock_verify.return_value = MagicMock(new_sign_count=1)

        # Credential belongs to self.user, but userHandle points to other_user
        spoofed_handle = user_uuid_to_handle(other_user.uuid)

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
                    "userHandle": bytes_to_base64url(spoofed_handle),
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("authentication failed", response.json()["error"].lower())

        # Verify the user is NOT logged in
        me_response = self.client.get("/api/users/@me/")
        self.assertEqual(me_response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("posthog.auth.verify_passkey_authentication_response")
    def test_login_rejects_nonexistent_user_handle(self, mock_verify):
        """userHandle pointing to a nonexistent user must be rejected."""
        from webauthn.helpers import bytes_to_base64url

        from posthog.api.webauthn import user_uuid_to_handle

        self.client.post("/api/webauthn/login/begin/")
        mock_verify.return_value = MagicMock(new_sign_count=1)

        # userHandle points to a UUID that doesn't exist
        fake_handle = user_uuid_to_handle(uuid.uuid4())

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
                    "userHandle": bytes_to_base64url(fake_handle),
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("authentication failed", response.json()["error"].lower())

    @patch("posthog.auth.verify_passkey_authentication_response")
    def test_login_enforces_sso_against_authenticated_user(self, mock_verify):
        """SSO enforcement must be checked against the cryptographically verified user,
        not the unverified userHandle."""
        from webauthn.helpers import bytes_to_base64url

        from posthog.api.webauthn import user_uuid_to_handle

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

        self.client.post("/api/webauthn/login/begin/")
        mock_verify.return_value = MagicMock(new_sign_count=1)

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
        self.assertIn("SSO", response.json()["error"])

        # Verify the user is NOT logged in
        me_response = self.client.get("/api/users/@me/")
        self.assertEqual(me_response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("posthog.auth.verify_passkey_authentication_response")
    def test_spoofed_user_handle_cannot_bypass_sso_enforcement(self, mock_verify):
        """An attacker with a valid passkey cannot bypass SSO enforcement by spoofing
        the userHandle to point to a user without SSO enforcement."""
        from webauthn.helpers import bytes_to_base64url

        from posthog.api.webauthn import user_uuid_to_handle

        # Create a second user in a different org without SSO enforcement
        from posthog.models.organization import Organization

        other_org = Organization.objects.create(name="No SSO Org")
        non_sso_user = User.objects.create_and_join(other_org, "nosso@other.com", "password123")

        # Enforce SSO for the credential owner's domain
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

        self.client.post("/api/webauthn/login/begin/")
        mock_verify.return_value = MagicMock(new_sign_count=1)

        # Attacker spoofs userHandle to point to the non-SSO user
        spoofed_handle = user_uuid_to_handle(non_sso_user.uuid)

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
                    "userHandle": bytes_to_base64url(spoofed_handle),
                },
            },
            format="json",
        )
        # The mismatch check should reject this before even reaching SSO checks
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("authentication failed", response.json()["error"].lower())

        # Verify the user is NOT logged in
        me_response = self.client.get("/api/users/@me/")
        self.assertEqual(me_response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("posthog.auth.verify_passkey_authentication_response")
    def test_spoofed_user_handle_records_failure_against_verified_user(self, mock_verify):
        """A spoofed userHandle mismatch must record an axes failure against the
        credential owner (verified user), so repeated attempts trigger rate limiting."""
        from webauthn.helpers import bytes_to_base64url

        from posthog.api.webauthn import user_uuid_to_handle

        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password123")
        spoofed_handle = user_uuid_to_handle(other_user.uuid)

        mock_verify.return_value = MagicMock(new_sign_count=1)

        with patch.object(
            WebAuthnLoginViewSet,
            "_handle_authentication_failure",
            wraps=WebAuthnLoginViewSet()._handle_authentication_failure,
        ) as mock_handle_failure:
            self.client.post("/api/webauthn/login/begin/")
            self.client.post(
                "/api/webauthn/login/complete/",
                {
                    "id": bytes_to_base64url(self.credential.credential_id),
                    "rawId": bytes_to_base64url(self.credential.credential_id),
                    "type": "public-key",
                    "response": {
                        "authenticatorData": "data",
                        "clientDataJSON": "data",
                        "signature": "sig",
                        "userHandle": bytes_to_base64url(spoofed_handle),
                    },
                },
                format="json",
            )

            mock_handle_failure.assert_called_once()
            # The failure must be recorded against the verified user (credential owner),
            # not the spoofed user from userHandle
            call_args = mock_handle_failure.call_args
            recorded_user = call_args[0][1]
            self.assertEqual(recorded_user.pk, self.user.pk)


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

    @patch("posthog.api.webauthn.send_passkey_removed_email")
    def test_delete_credential(self, mock_send_email):
        response = self.client.delete(f"/api/webauthn/credentials/{self.credential.pk}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        mock_send_email.delay.assert_called_once_with(self.user.id)
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

    @patch("posthog.api.webauthn.send_passkey_added_email")
    @patch("posthog.api.webauthn.verify_passkey_authentication_response")
    def test_verify_complete_sends_passkey_added_email(self, mock_verify, mock_send_email):
        unverified_credential = WebauthnCredential.objects.create(
            user=self.user,
            credential_id=b"unverified-credential-id",
            label="Unverified Passkey",
            public_key=b"public-key",
            algorithm=-7,
            counter=0,
            transports=["internal"],
            verified=False,
        )

        verify_begin_response = self.client.post(f"/api/webauthn/credentials/{unverified_credential.pk}/verify/")
        self.assertEqual(verify_begin_response.status_code, status.HTTP_200_OK)

        mock_verify.return_value = MagicMock(new_sign_count=1)

        verify_complete_response = self.client.post(
            f"/api/webauthn/credentials/{unverified_credential.pk}/verify_complete/",
            {},
            format="json",
        )
        self.assertEqual(verify_complete_response.status_code, status.HTTP_200_OK)
        self.assertTrue(verify_complete_response.json()["verified"])

        mock_send_email.delay.assert_called_once_with(self.user.id)

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
