import time
from datetime import datetime
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.views import APIView

from posthog.auth import (
    PersonalAPIKeyAuthentication,
    ProjectSecretAPIKeyAuthentication,
    SessionAuthentication,
    TemporaryTokenAuthentication,
)
from posthog.helpers.mfa_session import (
    clear_mfa_session_flags,
    is_mfa_session_expired,
    is_mfa_verified_in_session,
    set_mfa_verified_in_session,
)
from posthog.middleware import MFAEnforcementMiddleware
from posthog.models import Organization, User
from posthog.permissions import MFARequiredPermission


class TestMFASessionUtils(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _create_request(self):
        request = self.factory.get("/test/")
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()
        return request

    def test_set_mfa_verified_true(self):
        request = self._create_request()
        set_mfa_verified_in_session(request, verified=True)
        self.assertTrue(request.session.get("mfa_verified"))

    def test_set_mfa_verified_false(self):
        request = self._create_request()
        set_mfa_verified_in_session(request, verified=False)
        self.assertFalse(request.session.get("mfa_verified"))

    def test_is_mfa_verified_in_session_with_valid_session(self):
        request = self._create_request()
        request.session["mfa_verified"] = True
        request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = time.time()
        self.assertTrue(is_mfa_verified_in_session(request))

    def test_is_mfa_verified_in_session_without_flag(self):
        request = self._create_request()
        request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = time.time()
        self.assertFalse(is_mfa_verified_in_session(request))

    def test_is_mfa_verified_in_session_with_expired_session(self):
        request = self._create_request()
        request.session["mfa_verified"] = True
        request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = time.time() - (15 * 24 * 60 * 60)
        self.assertFalse(is_mfa_verified_in_session(request))

    def test_is_mfa_verified_in_session_without_session_timestamp(self):
        request = self._create_request()
        request.session["mfa_verified"] = True
        if settings.SESSION_COOKIE_CREATED_AT_KEY in request.session:
            del request.session[settings.SESSION_COOKIE_CREATED_AT_KEY]
        self.assertFalse(is_mfa_verified_in_session(request))

    def test_clear_mfa_session_flags(self):
        request = self._create_request()
        request.session["mfa_verified"] = True
        clear_mfa_session_flags(request)
        self.assertFalse(request.session.get("mfa_verified", False))

    def test_clear_mfa_session_flags_when_empty(self):
        request = self._create_request()
        clear_mfa_session_flags(request)
        self.assertFalse(request.session.get("mfa_verified", False))

    def test_is_mfa_session_expired_with_valid_session(self):
        request = self._create_request()
        request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = time.time()
        self.assertFalse(is_mfa_session_expired(request))

    def test_is_mfa_session_expired_with_expired_session(self):
        request = self._create_request()
        request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = time.time() - (15 * 24 * 60 * 60)
        self.assertTrue(is_mfa_session_expired(request))

    def test_is_mfa_session_expired_without_session_created_timestamp(self):
        request = self._create_request()
        self.assertTrue(is_mfa_session_expired(request))


class TestMFARequiredPermission(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.permission = MFARequiredPermission()
        self.view = Mock(spec=APIView)

        self.user = User(id=1, email="test@example.com")
        self.organization = Organization(id=1, name="Test Org", enforce_2fa=True)

    def _create_request_with_auth(self, auth_class, user=None):
        request = self.factory.get("/")
        request.user = user or self.user
        request.successful_authenticator = auth_class()
        return request

    def test_permission_granted_for_non_session_auth(self):
        request = self._create_request_with_auth(PersonalAPIKeyAuthentication)
        self.assertTrue(self.permission.has_permission(request, self.view))

    def test_permission_granted_for_unauthenticated_user(self):
        request = self._create_request_with_auth(SessionAuthentication, user=None)
        self.assertTrue(self.permission.has_permission(request, self.view))

    @patch("posthog.permissions.is_impersonated_session")
    def test_permission_granted_for_impersonated_session(self, mock_is_impersonated):
        mock_is_impersonated.return_value = True
        request = self._create_request_with_auth(SessionAuthentication)

        with patch.object(self.permission, "_get_organization", return_value=self.organization):
            self.assertTrue(self.permission.has_permission(request, self.view))

    def test_permission_granted_when_organization_does_not_enforce_2fa(self):
        org_no_2fa = Organization(id=2, name="No 2FA Org", enforce_2fa=False)
        request = self._create_request_with_auth(SessionAuthentication)

        with patch.object(self.permission, "_get_organization", return_value=org_no_2fa):
            self.assertTrue(self.permission.has_permission(request, self.view))

    def test_permission_granted_when_no_organization(self):
        request = self._create_request_with_auth(SessionAuthentication)

        with patch.object(self.permission, "_get_organization", return_value=None):
            self.assertTrue(self.permission.has_permission(request, self.view))

    @patch("posthog.permissions.default_device")
    @patch("posthog.permissions.is_impersonated_session")
    def test_permission_denied_when_user_has_no_2fa_device(self, mock_is_impersonated, mock_default_device):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = None
        request = self._create_request_with_auth(SessionAuthentication)

        with patch.object(self.permission, "_get_organization", return_value=self.organization):
            self.assertFalse(self.permission.has_permission(request, self.view))

    @patch("posthog.permissions.default_device")
    @patch("posthog.permissions.is_impersonated_session")
    @patch("posthog.permissions.is_mfa_verified_in_session")
    def test_permission_denied_when_session_not_verified(
        self, mock_is_mfa_verified, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = Mock()
        mock_is_mfa_verified.return_value = False
        request = self._create_request_with_auth(SessionAuthentication)

        with patch.object(self.permission, "_get_organization", return_value=self.organization):
            self.assertFalse(self.permission.has_permission(request, self.view))

    @patch("posthog.permissions.default_device")
    @patch("posthog.permissions.is_impersonated_session")
    @patch("posthog.permissions.is_mfa_verified_in_session")
    def test_permission_granted_when_fully_verified(
        self, mock_is_mfa_verified, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = Mock()
        mock_is_mfa_verified.return_value = True
        request = self._create_request_with_auth(SessionAuthentication)

        with patch.object(self.permission, "_get_organization", return_value=self.organization):
            self.assertTrue(self.permission.has_permission(request, self.view))


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
            self.assertEqual(response.status_code, 302)

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

    def test_handle_mfa_required_response_api(self):
        request = self._create_request(path="/api/test/")

        response = self.middleware._handle_mfa_required_response(request, "Test message")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.content.decode(), "Test message")
        self.assertEqual(response["Content-Type"], "application/json")

    def test_handle_mfa_required_response_non_api(self):
        request = self._create_request(path="/dashboard/")

        response = self.middleware._handle_mfa_required_response(request, "Test message")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")


class TestMFAImpersonationIntegration(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _create_request(self, path="/test/", user=None):
        request = self.factory.get(path)
        request.user = user or Mock(is_authenticated=True)

        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = datetime(2026, 1, 1).timestamp()
        request.session.save()

        return request

    @patch("posthog.middleware.is_impersonated_session")
    def test_impersonate_mfa_middleware_sets_mfa_verified_for_impersonated_sessions(self, mock_is_impersonated):
        from posthog.middleware import ImpersonateMiddleware

        mock_is_impersonated.return_value = True
        middleware = ImpersonateMiddleware(lambda req: HttpResponse("OK"))
        request = self._create_request()

        self.assertFalse(is_mfa_verified_in_session(request))

        response = middleware(request)

        self.assertTrue(is_mfa_verified_in_session(request))
        self.assertEqual(response.content.decode(), "OK")

    @patch("posthog.middleware.is_impersonated_session")
    @patch("posthog.middleware.default_device")
    def test_integration_admin_impersonating_user_in_2fa_org_without_2fa_setup(
        self, mock_default_device, mock_is_impersonated
    ):
        from posthog.middleware import ImpersonateMiddleware

        mock_is_impersonated.return_value = True
        mock_default_device.return_value = None

        def create_response(request):
            return HttpResponse("Success")

        mfa_middleware = MFAEnforcementMiddleware(create_response)
        impersonate_middleware = ImpersonateMiddleware(mfa_middleware)

        request = self._create_request(path="/dashboard/")
        request.successful_authenticator = SessionAuthentication()

        org = Mock(spec=Organization)
        org.enforce_2fa = True

        with patch.object(mfa_middleware, "_get_organization", return_value=org):
            response = impersonate_middleware(request)

        self.assertEqual(response.content.decode(), "Success")
        self.assertTrue(is_mfa_verified_in_session(request))


class TestAPIAuthenticationMFABypass(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.mfa_middleware = MFAEnforcementMiddleware(lambda request: None)

        self.user = Mock(spec=User)
        self.user.is_authenticated = True
        self.organization = Mock(spec=Organization)
        self.organization.enforce_2fa = True

    def _create_request(self, auth_class=None):
        request = self.factory.get("/api/users/@me/")
        request.user = self.user

        if auth_class:
            request.successful_authenticator = auth_class()

        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()

        return request

    def test_session_authentication_requires_mfa_check(self):
        request = self._create_request(SessionAuthentication)

        with patch.object(self.mfa_middleware, "_get_organization", return_value=self.organization):
            with patch("posthog.middleware.default_device", return_value=None):
                with patch("posthog.middleware.is_mfa_verified_in_session", return_value=False):
                    should_check = self.mfa_middleware._should_check_mfa(request)
                    self.assertTrue(should_check)

    def test_personal_api_key_authentication_bypasses_mfa_check(self):
        request = self._create_request(PersonalAPIKeyAuthentication)

        should_check = self.mfa_middleware._should_check_mfa(request)
        self.assertFalse(should_check)

    def test_temporary_token_authentication_bypasses_mfa_check(self):
        request = self._create_request(TemporaryTokenAuthentication)

        should_check = self.mfa_middleware._should_check_mfa(request)
        self.assertFalse(should_check)

    def test_project_secret_api_key_authentication_bypasses_mfa_check(self):
        request = self._create_request(ProjectSecretAPIKeyAuthentication)

        should_check = self.mfa_middleware._should_check_mfa(request)
        self.assertFalse(should_check)


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
        mock_form_instance = mock_totp_form.return_value
        mock_form_instance.is_valid.return_value = True

        session = self.client.session
        session["django_two_factor-hex"] = "1234567890abcdef1234"
        session.save()

        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.post("/api/users/@me/two_factor_validate/", {"token": "123456"})

        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()

        self.assertFalse(is_mfa_verified_in_session(request))

        response = self.client.post(f"/api/users/@me/two_factor_validate/", {"token": "123456"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True})

        test_request = factory.get("/")
        middleware.process_request(test_request)
        test_request.session = self.client.session

        self.assertTrue(is_mfa_verified_in_session(test_request))

        mock_totp_form.assert_called_once_with("1234567890abcdef1234", self.user, data={"token": "123456"})
        mock_form_instance.save.assert_called_once()
        mock_send_email.delay.assert_called_once_with(self.user.id)
