from unittest.mock import Mock, patch
from django.test import TestCase, RequestFactory
from django.http import HttpResponse
from django.contrib.auth.models import AnonymousUser

from posthog.auth import SessionAuthentication, PersonalAPIKeyAuthentication
from posthog.models import User, Organization
from posthog.middleware import MFAEnforcementMiddleware


class TestMFAEnforcementMiddleware(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = MFAEnforcementMiddleware(lambda request: HttpResponse("OK"))

        self.user = Mock(spec=User)
        self.user.is_authenticated = True
        self.organization = Mock(spec=Organization)
        self.organization.enforce_2fa = True

    def _create_request(self, path="/test/", user=None, auth_class=None):
        request = self.factory.get(path)
        request.user = user or self.user
        if auth_class:
            request.successful_authenticator = auth_class()
        return request

    def test_middleware_skips_unauthenticated_users(self):
        request = self._create_request(user=AnonymousUser())
        response = self.middleware(request)
        self.assertEqual(response.content.decode(), "OK")

    def test_middleware_skips_non_authenticated_users(self):
        user = Mock()
        user.is_authenticated = False
        request = self._create_request(user=user)
        response = self.middleware(request)
        self.assertEqual(response.content.decode(), "OK")

    def test_middleware_skips_api_key_authentication(self):
        request = self._create_request(auth_class=PersonalAPIKeyAuthentication)
        response = self.middleware(request)
        self.assertEqual(response.content.decode(), "OK")

    def test_middleware_skips_whitelisted_paths(self):
        whitelisted_paths = [
            "/static/favicon.ico",
            "/api/users/@me/two_factor_start_setup/",
            "/api/users/@me/two_factor_validate/",
            "/api/users/@me/two_factor_status/",
            "/logout/",
            "/admin/",
            "/_health",
        ]

        for path in whitelisted_paths:
            request = self._create_request(path=path, auth_class=SessionAuthentication)
            response = self.middleware(request)
            self.assertEqual(response.content.decode(), "OK", f"Path {path} should be whitelisted")

    @patch("posthog.middleware.is_impersonated_session")
    def test_middleware_skips_impersonated_sessions(self, mock_is_impersonated):
        mock_is_impersonated.return_value = True
        request = self._create_request(auth_class=SessionAuthentication)

        with patch.object(self.middleware, "_get_organization", return_value=self.organization):
            response = self.middleware(request)
            self.assertEqual(response.content.decode(), "OK")

    def test_middleware_allows_when_organization_not_enforce_2fa(self):
        org_no_2fa = Mock(spec=Organization)
        org_no_2fa.enforce_2fa = False
        request = self._create_request(auth_class=SessionAuthentication)

        with patch.object(self.middleware, "_get_organization", return_value=org_no_2fa):
            response = self.middleware(request)
            self.assertEqual(response.content.decode(), "OK")

    def test_middleware_allows_when_no_organization(self):
        request = self._create_request(auth_class=SessionAuthentication)

        with patch.object(self.middleware, "_get_organization", return_value=None):
            response = self.middleware(request)
            self.assertEqual(response.content.decode(), "OK")

    @patch("posthog.middleware.default_device")
    @patch("posthog.middleware.is_impersonated_session")
    def test_middleware_blocks_when_no_2fa_device_api_request(self, mock_is_impersonated, mock_default_device):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = None
        request = self._create_request(path="/api/test/", auth_class=SessionAuthentication)

        with patch.object(self.middleware, "_get_organization", return_value=self.organization):
            response = self.middleware(request)
            self.assertEqual(response.status_code, 403)
            self.assertIn("2FA setup required", response.content.decode())

    @patch("posthog.middleware.default_device")
    @patch("posthog.middleware.is_impersonated_session")
    def test_middleware_blocks_when_no_2fa_device_non_api_request(self, mock_is_impersonated, mock_default_device):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = None
        request = self._create_request(path="/dashboard/", auth_class=SessionAuthentication)

        with patch.object(self.middleware, "_get_organization", return_value=self.organization):
            response = self.middleware(request)
            self.assertEqual(response.status_code, 302)  # Redirect

    @patch("posthog.middleware.default_device")
    @patch("posthog.middleware.is_impersonated_session")
    @patch("posthog.middleware.is_mfa_verified_in_session")
    def test_middleware_blocks_when_session_not_verified_api_request(
        self, mock_is_mfa_verified, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = Mock()
        mock_is_mfa_verified.return_value = False
        request = self._create_request(path="/api/test/", auth_class=SessionAuthentication)

        with patch.object(self.middleware, "_get_organization", return_value=self.organization):
            response = self.middleware(request)
            self.assertEqual(response.status_code, 403)
            self.assertIn("2FA verification required", response.content.decode())

    @patch("posthog.middleware.default_device")
    @patch("posthog.middleware.is_impersonated_session")
    @patch("posthog.middleware.is_mfa_verified_in_session")
    def test_middleware_allows_when_fully_verified(
        self, mock_is_mfa_verified, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = Mock()
        mock_is_mfa_verified.return_value = True
        request = self._create_request(auth_class=SessionAuthentication)

        with patch.object(self.middleware, "_get_organization", return_value=self.organization):
            response = self.middleware(request)
            self.assertEqual(response.content.decode(), "OK")

    def test_should_check_mfa_with_no_authenticator_attribute(self):
        request = self._create_request()
        # Don't set successful_authenticator attribute
        if hasattr(request, "successful_authenticator"):
            delattr(request, "successful_authenticator")

        result = self.middleware._should_check_mfa(request)
        self.assertFalse(result)

    def test_should_check_mfa_with_authenticator_without_class(self):
        request = self._create_request()
        request.successful_authenticator = Mock()
        # Delete __class__ attribute to simulate missing class info
        if hasattr(request.successful_authenticator, "__class__"):
            delattr(request.successful_authenticator, "__class__")

        result = self.middleware._should_check_mfa(request)
        self.assertFalse(result)

    def test_get_organization_returns_user_organization(self):
        user = Mock(spec=User)
        user.organization = self.organization

        result = self.middleware._get_organization(user)
        self.assertEqual(result, self.organization)

    def test_get_organization_returns_none_on_attribute_error(self):
        user = Mock()
        # Remove the organization attribute to trigger AttributeError
        if hasattr(user, "organization"):
            delattr(user, "organization")

        result = self.middleware._get_organization(user)
        self.assertIsNone(result)

    def test_handle_mfa_required_response_api(self):
        request = self._create_request(path="/api/test/")

        response = self.middleware._handle_mfa_required_response(request, "Test message")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.content.decode(), "Test message")
        self.assertEqual(response["Content-Type"], "application/json")

    def test_handle_mfa_required_response_non_api(self):
        request = self._create_request(path="/dashboard/")

        response = self.middleware._handle_mfa_required_response(request, "Test message")

        self.assertEqual(response.status_code, 302)  # Redirect
        self.assertEqual(response.url, "/")
