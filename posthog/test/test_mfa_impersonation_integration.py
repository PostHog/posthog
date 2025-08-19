from unittest.mock import Mock, patch
from django.test import TestCase, RequestFactory
from django.http import HttpResponse
from django.contrib.sessions.middleware import SessionMiddleware
from datetime import datetime

from posthog.models import User, Organization
from posthog.middleware import AutoLogoutImpersonateMiddleware, ImpersonateMiddleware, MFAEnforcementMiddleware
from posthog.auth import SessionAuthentication


class TestMFAImpersonationIntegration(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.impersonation_middleware = AutoLogoutImpersonateMiddleware(lambda request: HttpResponse("OK"))
        self.impersonate_mfa_middleware = ImpersonateMiddleware(lambda request: HttpResponse("OK"))
        self.mfa_middleware = MFAEnforcementMiddleware(lambda request: HttpResponse("OK"))

        self.user = Mock(spec=User)
        self.user.is_authenticated = True
        self.organization = Mock(spec=Organization)
        self.organization.enforce_2fa = True

    def _create_request(self, path="/test/", user=None):
        request = self.factory.get(path)
        request.user = user or self.user
        request.successful_authenticator = SessionAuthentication()

        # Add session middleware to the request
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()

        return request

    @patch("posthog.middleware.get_impersonated_session_expires_at")
    def test_impersonation_middleware_skips_non_impersonated_sessions(self, mock_get_expires):
        mock_get_expires.return_value = None
        request = self._create_request()

        response = self.impersonation_middleware(request)
        self.assertEqual(response.content.decode(), "OK")

    @patch("posthog.middleware.is_impersonated_session")
    @patch("posthog.middleware.is_mfa_verified_in_session")
    @patch("posthog.middleware.set_mfa_verified_in_session")
    def test_impersonate_mfa_middleware_sets_mfa_verified_for_impersonated_sessions(
        self, mock_set_mfa, mock_is_mfa_verified, mock_is_impersonated
    ):
        mock_is_impersonated.return_value = True
        mock_is_mfa_verified.return_value = False
        request = self._create_request()

        response = self.impersonate_mfa_middleware(request)

        mock_set_mfa.assert_called_once_with(request)
        self.assertEqual(response.content.decode(), "OK")

    @patch("posthog.middleware.is_impersonated_session")
    @patch("posthog.middleware.is_mfa_verified_in_session")
    @patch("posthog.middleware.set_mfa_verified_in_session")
    def test_impersonate_mfa_middleware_skips_setting_mfa_if_already_verified(
        self, mock_set_mfa, mock_is_mfa_verified, mock_is_impersonated
    ):
        mock_is_impersonated.return_value = True
        mock_is_mfa_verified.return_value = True
        request = self._create_request()

        response = self.impersonate_mfa_middleware(request)

        mock_set_mfa.assert_not_called()
        self.assertEqual(response.content.decode(), "OK")

    @patch("posthog.middleware.is_impersonated_session")
    @patch("posthog.middleware.set_mfa_verified_in_session")
    def test_impersonate_mfa_middleware_skips_setting_mfa_for_unauthenticated_users(
        self, mock_set_mfa, mock_is_impersonated
    ):
        mock_is_impersonated.return_value = True

        # Create an unauthenticated user
        unauthenticated_user = Mock(spec=User)
        unauthenticated_user.is_authenticated = False
        request = self._create_request(user=unauthenticated_user)

        response = self.impersonate_mfa_middleware(request)

        mock_set_mfa.assert_not_called()
        self.assertEqual(response.content.decode(), "OK")

    @patch("posthog.middleware.is_impersonated_session")
    @patch("posthog.middleware.set_mfa_verified_in_session")
    def test_impersonate_mfa_middleware_skips_non_impersonated_sessions(self, mock_set_mfa, mock_is_impersonated):
        mock_is_impersonated.return_value = False
        request = self._create_request()

        response = self.impersonate_mfa_middleware(request)

        mock_set_mfa.assert_not_called()
        self.assertEqual(response.content.decode(), "OK")

    @patch("posthog.middleware.get_impersonated_session_expires_at")
    @patch("posthog.middleware.is_mfa_verified_in_session")
    @patch("posthog.middleware.set_mfa_verified_in_session")
    def test_mfa_middleware_allows_impersonated_sessions_through(
        self, mock_set_mfa, mock_is_mfa_verified, mock_get_expires
    ):
        request = self._create_request()

        with patch("posthog.middleware.is_impersonated_session", return_value=True):
            with patch.object(self.mfa_middleware, "_get_organization", return_value=self.organization):
                response = self.mfa_middleware(request)
                self.assertEqual(response.content.decode(), "OK")

    @patch("posthog.middleware.default_device")
    def test_integration_admin_impersonating_user_in_2fa_org_without_2fa_setup(self, mock_default_device):
        mock_default_device.return_value = None
        request = self._create_request()

        with patch("posthog.middleware.is_impersonated_session", return_value=True):
            with patch("posthog.middleware.is_mfa_verified_in_session", return_value=False) as mock_is_verified:
                with patch("posthog.middleware.set_mfa_verified_in_session") as mock_set_verified:
                    # First, the ImpersonateMiddleware sets MFA verified
                    mfa_response = self.impersonate_mfa_middleware(request)
                    self.assertEqual(mfa_response.content.decode(), "OK")
                    mock_set_verified.assert_called_once_with(request)

                    # Then, the MFAEnforcementMiddleware allows the request through
                    mock_is_verified.return_value = True
                    with patch.object(self.mfa_middleware, "_get_organization", return_value=self.organization):
                        enforcement_response = self.mfa_middleware(request)
                        self.assertEqual(enforcement_response.content.decode(), "OK")

    @patch("posthog.middleware.default_device")
    def test_integration_admin_impersonating_user_in_2fa_org_with_2fa_setup(self, mock_default_device):
        mock_default_device.return_value = Mock()
        request = self._create_request()

        with patch("posthog.middleware.is_impersonated_session", return_value=True):
            with patch("posthog.middleware.is_mfa_verified_in_session", return_value=False) as mock_is_verified:
                with patch("posthog.middleware.set_mfa_verified_in_session") as mock_set_verified:
                    # First, the ImpersonateMiddleware sets MFA verified
                    mfa_response = self.impersonate_mfa_middleware(request)
                    self.assertEqual(mfa_response.content.decode(), "OK")
                    mock_set_verified.assert_called_once_with(request)

                    # Then, the MFAEnforcementMiddleware allows the request through
                    mock_is_verified.return_value = True
                    with patch.object(self.mfa_middleware, "_get_organization", return_value=self.organization):
                        enforcement_response = self.mfa_middleware(request)
                        self.assertEqual(enforcement_response.content.decode(), "OK")

    def test_integration_admin_impersonating_user_in_non_2fa_org(self):
        org_no_2fa = Mock(spec=Organization)
        org_no_2fa.enforce_2fa = False
        request = self._create_request()

        with patch("posthog.middleware.is_impersonated_session", return_value=True):
            with patch("posthog.middleware.is_mfa_verified_in_session", return_value=False) as mock_is_verified:
                with patch("posthog.middleware.set_mfa_verified_in_session") as mock_set_verified:
                    # First, the ImpersonateMiddleware sets MFA verified
                    mfa_response = self.impersonate_mfa_middleware(request)
                    self.assertEqual(mfa_response.content.decode(), "OK")
                    mock_set_verified.assert_called_once_with(request)

                    # Then, the MFAEnforcementMiddleware allows the request through (org doesn't require 2FA)
                    mock_is_verified.return_value = True
                    with patch.object(self.mfa_middleware, "_get_organization", return_value=org_no_2fa):
                        enforcement_response = self.mfa_middleware(request)
                        self.assertEqual(enforcement_response.content.decode(), "OK")

    @patch("posthog.middleware.get_impersonated_session_expires_at")
    def test_impersonation_middleware_handles_expired_sessions(self, mock_get_expires):
        past_time = datetime(2020, 1, 1)
        mock_get_expires.return_value = past_time
        request = self._create_request(path="/api/test/")

        response = self.impersonation_middleware(request)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Impersonation session has expired", response.content.decode())
