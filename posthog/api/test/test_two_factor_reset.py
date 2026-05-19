import time
import datetime

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework import status

from posthog.api.two_factor_reset import TwoFactorResetVerifier
from posthog.models import User
from posthog.models.webauthn_credential import WebauthnCredential


class TestTwoFactorReset(APIBaseTest):
    """Tests for the 2FA reset functionality."""

    def setUp(self):
        super().setUp()
        # Log out the default user - we'll use half-auth session instead
        self.client.logout()

        # Create TOTP device for the user
        self.totp_device = TOTPDevice.objects.create(
            user=self.user,
            name="Test Device",
            confirmed=True,
        )
        # Create static device with backup codes
        self.static_device = StaticDevice.objects.create(
            user=self.user,
            name="Backup Codes",
            confirmed=True,
        )
        StaticToken.objects.create(device=self.static_device, token="backup1234")
        StaticToken.objects.create(device=self.static_device, token="backup5678")

    def _setup_2fa_reset(self):
        """Helper to set up 2FA reset state and return a valid token."""
        self.user.requested_2fa_reset_at = datetime.datetime.now(datetime.UTC)
        self.user.save(update_fields=["requested_2fa_reset_at"])
        return TwoFactorResetVerifier.create_token(self.user)

    def _setup_half_auth_session(self, user=None):
        """
        Set up a half-auth session state (user authenticated with credentials but not 2FA).
        This simulates what happens when a user enters correct email/password but hasn't
        completed the 2FA step yet.
        """
        if user is None:
            user = self.user
        session = self.client.session
        session["user_authenticated_but_no_2fa"] = user.pk
        session["user_authenticated_time"] = int(time.time())
        session.save()

    # Token validation tests

    def test_can_validate_token(self):
        """Test that a valid 2FA reset token can be validated with half-auth session."""
        token = self._setup_2fa_reset()
        self._setup_half_auth_session()

        response = self.client.get(f"/api/reset_2fa/{self.user.uuid}/?token={token}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["success"])
        self.assertEqual(response.json()["token"], token)

    def test_cannot_validate_without_token(self):
        """Test that validation fails without a token."""
        self._setup_half_auth_session()

        response = self.client.get(f"/api/reset_2fa/{self.user.uuid}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "Token is required.")

    def test_cannot_validate_without_half_auth_session(self):
        """Test that validation fails without a half-auth session."""
        token = self._setup_2fa_reset()

        response = self.client.get(f"/api/reset_2fa/{self.user.uuid}/?token={token}")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertTrue(response.json()["requires_login"])
        self.assertEqual(response.json()["error"], "You must log in with your credentials first.")

    def test_cannot_validate_with_expired_half_auth_session(self):
        """Test that validation fails when half-auth session has expired (24 hours for reset flow)."""
        token = self._setup_2fa_reset()

        # Set up session with an old timestamp (more than 24 hours ago)
        session = self.client.session
        session["user_authenticated_but_no_2fa"] = self.user.pk
        session["user_authenticated_time"] = int(time.time()) - 86500  # 24 hours + 100 seconds ago
        session.save()

        response = self.client.get(f"/api/reset_2fa/{self.user.uuid}/?token={token}")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertTrue(response.json()["requires_login"])
        self.assertEqual(response.json()["error"], "Your login session has expired. Please log in again.")

    def test_cannot_validate_invalid_token(self):
        """Test that validation fails with an invalid token."""
        self._setup_2fa_reset()
        self._setup_half_auth_session()

        response = self.client.get(f"/api/reset_2fa/{self.user.uuid}/?token=invalid_token")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "This reset link is invalid or has expired.")

    def test_cannot_validate_expired_token(self):
        """Test that tokens expire after 24 hours."""
        token = self._setup_2fa_reset()

        # Move time forward by more than 24 hours
        with freeze_time(timezone.now() + datetime.timedelta(hours=24, minutes=1)):
            self._setup_half_auth_session()
            response = self.client.get(f"/api/reset_2fa/{self.user.uuid}/?token={token}")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "This reset link is invalid or has expired.")

    def test_cannot_validate_with_invalid_user(self):
        """Test that validation fails with an invalid user UUID."""
        token = self._setup_2fa_reset()
        self._setup_half_auth_session()

        response = self.client.get(f"/api/reset_2fa/00000000-0000-0000-0000-000000000000/?token={token}")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "This reset link is invalid or has expired.")

    def test_cannot_validate_for_different_user(self):
        """Test that validation fails when half-auth user doesn't match link user."""
        token = self._setup_2fa_reset()

        # Create and set up half-auth for a different user
        other_user = User.objects.create_user(
            email="other@posthog.com",
            password="other-password",
            first_name="Other",
        )
        self._setup_half_auth_session(user=other_user)

        response = self.client.get(f"/api/reset_2fa/{self.user.uuid}/?token={token}")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["error"], "This reset link is for a different account.")

    # 2FA reset execution tests

    @patch("posthog.tasks.email.send_two_factor_auth_disabled_email.delay")
    def test_can_reset_2fa(self, mock_send_email):
        """Test that a half-authed user can reset their own 2FA."""
        token = self._setup_2fa_reset()
        self._setup_half_auth_session()

        # Verify TOTP device exists before reset
        self.assertTrue(TOTPDevice.objects.filter(user=self.user).exists())
        self.assertTrue(StaticDevice.objects.filter(user=self.user).exists())

        response = self.client.post(f"/api/reset_2fa/{self.user.uuid}/", {"token": token})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["success"])

        # Verify TOTP device was deleted
        self.assertFalse(TOTPDevice.objects.filter(user=self.user).exists())

        # Verify static device was deleted
        self.assertFalse(StaticDevice.objects.filter(user=self.user).exists())

        # Verify passkey 2FA was disabled
        self.user.refresh_from_db()
        self.assertFalse(self.user.passkeys_enabled_for_2fa)

        # Verify reset timestamp was cleared
        self.assertIsNone(self.user.requested_2fa_reset_at)

        # Verify email notification was sent
        mock_send_email.assert_called_once_with(self.user.pk)

    @patch("posthog.tasks.email.send_two_factor_auth_disabled_email.delay")
    def test_reset_clears_half_auth_session(self, mock_send_email):
        """Test that 2FA reset clears the half-auth session state."""
        token = self._setup_2fa_reset()
        self._setup_half_auth_session()

        response = self.client.post(f"/api/reset_2fa/{self.user.uuid}/", {"token": token})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify session keys were cleared
        session = self.client.session
        self.assertIsNone(session.get("user_authenticated_but_no_2fa"))
        self.assertIsNone(session.get("user_authenticated_time"))

    def test_cannot_reset_2fa_without_token(self):
        """Test that 2FA reset fails without a token."""
        self._setup_half_auth_session()

        response = self.client.post(f"/api/reset_2fa/{self.user.uuid}/", {})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "Token is required.")

    def test_cannot_reset_2fa_with_invalid_token(self):
        """Test that 2FA reset fails with an invalid token."""
        self._setup_2fa_reset()
        self._setup_half_auth_session()

        response = self.client.post(f"/api/reset_2fa/{self.user.uuid}/", {"token": "invalid_token"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "This reset link is invalid or has expired.")

    def test_cannot_reset_2fa_without_half_auth_session(self):
        """Test that unauthenticated users cannot reset 2FA."""
        token = self._setup_2fa_reset()

        response = self.client.post(f"/api/reset_2fa/{self.user.uuid}/", {"token": token})

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertTrue(response.json()["requires_login"])
        self.assertEqual(response.json()["error"], "You must log in with your credentials first.")

    def test_cannot_reset_2fa_for_different_user(self):
        """Test that users cannot reset 2FA for other users."""
        token = self._setup_2fa_reset()

        # Create and set up half-auth for a different user
        other_user = User.objects.create_user(
            email="other@posthog.com",
            password="other-password",
            first_name="Other",
        )
        self._setup_half_auth_session(user=other_user)

        response = self.client.post(f"/api/reset_2fa/{self.user.uuid}/", {"token": token})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["error"], "This reset link is for a different account.")

    def test_new_reset_request_invalidates_old_token(self):
        """Test that requesting a new reset invalidates the old token."""
        # Get first token at time T
        with freeze_time("2024-01-01 12:00:00"):
            token1 = self._setup_2fa_reset()

        # Request a new reset at time T+1 (which updates requested_2fa_reset_at)
        with freeze_time("2024-01-01 12:00:01"):
            self.user.requested_2fa_reset_at = datetime.datetime.now(datetime.UTC)
            self.user.save(update_fields=["requested_2fa_reset_at"])
            token2 = TwoFactorResetVerifier.create_token(self.user)

            self._setup_half_auth_session()

            # First token should be invalid now (hash value changed)
            response = self.client.get(f"/api/reset_2fa/{self.user.uuid}/?token={token1}")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

            # Second token should be valid
            response = self.client.get(f"/api/reset_2fa/{self.user.uuid}/?token={token2}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestTwoFactorResetWithPasskeys(APIBaseTest):
    """Tests for 2FA reset with passkeys enabled."""

    def setUp(self):
        super().setUp()
        # Log out the default user - we'll use half-auth session instead
        self.client.logout()

        # Enable passkeys for 2FA
        self.user.passkeys_enabled_for_2fa = True
        self.user.save()

        # Create a verified passkey
        self.passkey = WebauthnCredential.objects.create(
            user=self.user,
            credential_id=b"test_credential_id",
            public_key=b"test_public_key",
            algorithm=-7,
            label="Test Passkey",
            verified=True,
        )

    def _setup_2fa_reset(self):
        """Helper to set up 2FA reset state and return a valid token."""
        self.user.requested_2fa_reset_at = datetime.datetime.now(datetime.UTC)
        self.user.save(update_fields=["requested_2fa_reset_at"])
        return TwoFactorResetVerifier.create_token(self.user)

    def _setup_half_auth_session(self, user=None):
        """Set up a half-auth session state."""
        if user is None:
            user = self.user
        session = self.client.session
        session["user_authenticated_but_no_2fa"] = user.pk
        session["user_authenticated_time"] = int(time.time())
        session.save()

    @patch("posthog.tasks.email.send_two_factor_auth_disabled_email.delay")
    def test_reset_disables_passkey_2fa_but_keeps_passkeys(self, mock_send_email):
        """Test that 2FA reset disables passkey-based 2FA but keeps the passkeys."""
        token = self._setup_2fa_reset()
        self._setup_half_auth_session()

        # Verify passkey exists and 2FA is enabled
        self.assertTrue(WebauthnCredential.objects.filter(user=self.user, verified=True).exists())
        self.assertTrue(self.user.passkeys_enabled_for_2fa)

        response = self.client.post(f"/api/reset_2fa/{self.user.uuid}/", {"token": token})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Passkey should still exist
        self.assertTrue(WebauthnCredential.objects.filter(user=self.user, verified=True).exists())

        # But passkey 2FA should be disabled
        self.user.refresh_from_db()
        self.assertFalse(self.user.passkeys_enabled_for_2fa)


class TestTwoFactorResetLoginBypass(APIBaseTest):
    """Tests for the 2FA bypass during login when user has a valid reset link."""

    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        super().setUp()

        # Set a known password for login tests
        self.password = "test-password-123"
        self.user.set_password(self.password)
        self.user.save()

        # Create TOTP device for the user (this makes 2FA required)
        # Note: device must be named "default" for default_device() to find it
        self.totp_device = self.user.totpdevice_set.create(  # type: ignore
            name="default",
            confirmed=True,
        )

    def _setup_2fa_reset(self):
        """Helper to set up 2FA reset state and return a valid token."""
        self.user.requested_2fa_reset_at = datetime.datetime.now(datetime.UTC)
        self.user.save(update_fields=["requested_2fa_reset_at"])
        return TwoFactorResetVerifier.create_token(self.user)

    def test_login_without_reset_link_requires_2fa(self):
        """Test that normal login still requires 2FA."""
        response = self.client.post(
            "/api/login",
            {"email": self.user.email, "password": self.password},
        )

        # Should require 2FA
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()["code"], "2fa_required")
