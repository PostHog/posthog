from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.auth import get_user_model

from posthog.models import Organization
from posthog.helpers.mfa_session import is_mfa_verified_in_session


class TestUserMFASessionIntegration(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email="test@example.com", password="testpassword", first_name="Test", last_name="User"
        )
        self.organization, _, self.team = Organization.objects.bootstrap(self.user)

        self.client = APIClient()
        self.client.force_login(self.user)

    @patch("posthog.api.user.TOTPDeviceForm")
    @patch("posthog.api.user.send_two_factor_auth_enabled_email")
    def test_two_factor_validate_sets_mfa_session_flag(self, mock_send_email, mock_totp_form):
        # Setup form mock
        mock_form_instance = mock_totp_form.return_value
        mock_form_instance.is_valid.return_value = True

        # Setup session state - this simulates the 2FA setup process
        session = self.client.session
        session["django_two_factor-hex"] = "1234567890abcdef1234"
        session.save()

        # Before validation, MFA should not be verified in session
        # We need to get a proper request object to test this
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.post("/api/users/@me/two_factor_validate/", {"token": "123456"})

        # Add session middleware to the test request
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()

        # Initially, MFA should not be verified
        self.assertFalse(is_mfa_verified_in_session(request))

        # Make the actual API call
        response = self.client.post(f"/api/users/@me/two_factor_validate/", {"token": "123456"})

        # Verify the API call succeeded
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True})

        # Now check that MFA is verified in the session for this client
        # Get the session from the test client
        test_request = factory.get("/")
        middleware.process_request(test_request)
        test_request.session = self.client.session

        # MFA should now be verified in the session
        self.assertTrue(is_mfa_verified_in_session(test_request))

        # Verify other expected behavior
        mock_totp_form.assert_called_once_with("1234567890abcdef1234", self.user, data={"token": "123456"})
        mock_form_instance.save.assert_called_once()
        mock_send_email.delay.assert_called_once_with(self.user.id)
