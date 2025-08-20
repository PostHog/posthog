import time
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from rest_framework.exceptions import PermissionDenied
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


class TestSessionAuthenticationMFA(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.auth = SessionAuthentication()

        self.user = Mock(spec=User)
        self.user.is_authenticated = True
        self.user.is_active = True
        self.organization = Mock(spec=Organization)
        self.organization.enforce_2fa = True

    def _create_drf_request(self, path="/test/", user=None):
        request_factory = RequestFactory()
        http_request = request_factory.get(path)
        http_request.user = user if user is not None else self.user

        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(http_request)
        http_request.session.save()

        request = self.factory.get(path)
        request._request = http_request
        return request

    @patch("posthog.helpers.mfa_session.default_device")
    @patch("posthog.helpers.mfa_session.is_impersonated_session")
    def test_authentication_skips_impersonated_sessions(self, mock_is_impersonated, mock_default_device):
        mock_is_impersonated.return_value = True
        mock_default_device.return_value = Mock()
        request = self._create_drf_request()

        with patch.object(self.user, "organization", self.organization), patch.object(self.auth, "enforce_csrf"):
            result = self.auth.authenticate(request)
            self.assertEqual(result, (self.user, None))

    @patch("loginas.utils.is_impersonated_session")
    def test_authentication_allows_when_organization_not_enforce_2fa(self, mock_is_impersonated):
        mock_is_impersonated.return_value = False
        org_no_2fa = Mock(spec=Organization)
        org_no_2fa.enforce_2fa = False
        request = self._create_drf_request()

        with patch.object(self.user, "organization", org_no_2fa), patch.object(self.auth, "enforce_csrf"):
            result = self.auth.authenticate(request)
            self.assertEqual(result, (self.user, None))

    @patch("posthog.helpers.mfa_session.default_device")
    @patch("posthog.helpers.mfa_session.is_impersonated_session")
    def test_authentication_raises_permission_denied_when_no_2fa_device(
        self, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = None
        request = self._create_drf_request()

        with patch.object(self.user, "organization", self.organization), patch.object(self.auth, "enforce_csrf"):
            with self.assertRaises(PermissionDenied) as cm:
                self.auth.authenticate(request)
            self.assertEqual(str(cm.exception.detail), "2FA setup required")
            self.assertEqual(cm.exception.get_codes(), "mfa_setup_required")

    @patch("posthog.helpers.mfa_session.default_device")
    @patch("posthog.helpers.mfa_session.is_impersonated_session")
    @patch("posthog.helpers.mfa_session.is_mfa_verified_in_session")
    def test_authentication_raises_permission_denied_when_session_not_verified(
        self, mock_is_mfa_verified, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = Mock()
        mock_is_mfa_verified.return_value = False
        request = self._create_drf_request()

        with patch.object(self.user, "organization", self.organization), patch.object(self.auth, "enforce_csrf"):
            with self.assertRaises(PermissionDenied) as cm:
                self.auth.authenticate(request)
            self.assertEqual(str(cm.exception.detail), "2FA verification required")
            self.assertEqual(cm.exception.get_codes(), "mfa_verification_required")

    @patch("posthog.helpers.mfa_session.default_device")
    @patch("posthog.helpers.mfa_session.is_impersonated_session")
    @patch("posthog.helpers.mfa_session.is_mfa_verified_in_session")
    def test_authentication_succeeds_when_fully_verified(
        self, mock_is_mfa_verified, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = Mock()
        mock_is_mfa_verified.return_value = True
        request = self._create_drf_request()

        with patch.object(self.user, "organization", self.organization), patch.object(self.auth, "enforce_csrf"):
            result = self.auth.authenticate(request)
            self.assertEqual(result, (self.user, None))

    @patch("posthog.helpers.mfa_session.default_device")
    @patch("posthog.helpers.mfa_session.is_impersonated_session")
    def test_authentication_skips_whitelisted_paths(self, mock_is_impersonated, mock_default_device):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = None

        whitelisted_paths = [
            "/api/users/@me/two_factor_start_setup/",
            "/api/users/@me/two_factor_validate/",
            "/logout/",
            "/api/logout/",
            "/_health/",
            "/static/css/app.css",
            "/uploaded_media/file.png",
        ]

        for path in whitelisted_paths:
            request = self._create_drf_request(path=path)

            with patch.object(self.user, "organization", self.organization), patch.object(self.auth, "enforce_csrf"):
                result = self.auth.authenticate(request)
                self.assertEqual(result, (self.user, None), f"Path {path} should be whitelisted")

    @patch("posthog.helpers.mfa_session.default_device")
    @patch("posthog.helpers.mfa_session.is_impersonated_session")
    def test_authentication_enforces_mfa_on_non_whitelisted_paths(self, mock_is_impersonated, mock_default_device):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = None

        non_whitelisted_paths = [
            "/api/users/@me/",
            "/api/projects/1/insights/",
            "/dashboard/123",
            "/insights/abc123",
        ]

        for path in non_whitelisted_paths:
            request = self._create_drf_request(path=path)

            with patch.object(self.user, "organization", self.organization), patch.object(self.auth, "enforce_csrf"):
                with self.assertRaises(PermissionDenied) as cm:
                    self.auth.authenticate(request)
                self.assertEqual(str(cm.exception.detail), "2FA setup required", f"Path {path} should require MFA")

    def test_authentication_returns_none_for_inactive_user(self):
        inactive_user = Mock(spec=User)
        inactive_user.is_authenticated = True
        inactive_user.is_active = False
        request = self._create_drf_request(user=inactive_user)

        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    def test_authentication_returns_none_for_no_user(self):
        request = self.factory.get("/test/")
        http_request = Mock()
        http_request.user = None
        request._request = http_request

        result = self.auth.authenticate(request)
        self.assertIsNone(result)


class TestMFAImpersonationIntegration(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.auth = SessionAuthentication()

    def _create_drf_request(self, path="/test/", user=None):
        request_factory = RequestFactory()
        http_request = request_factory.get(path)
        http_request.user = user if user is not None else Mock(is_authenticated=True, is_active=True)

        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(http_request)
        http_request.session.save()

        request = self.factory.get(path)
        request._request = http_request
        return request

    @patch("posthog.auth.is_impersonated_session")
    def test_session_authentication_bypasses_mfa_for_impersonated_sessions(self, mock_is_impersonated):
        mock_is_impersonated.return_value = True
        user = Mock(is_authenticated=True, is_active=True)
        org = Mock(spec=Organization)
        org.enforce_2fa = True
        user.organization = org

        request = self._create_drf_request(user=user)

        with patch.object(self.auth, "enforce_csrf"):
            result = self.auth.authenticate(request)
            self.assertEqual(result, (user, None))

    @patch("posthog.auth.is_impersonated_session")
    @patch("posthog.auth.default_device")
    def test_session_authentication_enforces_mfa_for_non_impersonated_sessions(
        self, mock_default_device, mock_is_impersonated
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = None

        user = Mock(is_authenticated=True, is_active=True)
        org = Mock(spec=Organization)
        org.enforce_2fa = True
        user.organization = org

        request = self._create_drf_request(user=user)

        with patch.object(self.auth, "enforce_csrf"):
            with self.assertRaises(PermissionDenied) as cm:
                self.auth.authenticate(request)
            self.assertEqual(str(cm.exception.detail), "2FA setup required")


class TestAPIAuthenticationMFABypass(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def test_session_authentication_enforces_mfa(self):
        auth = SessionAuthentication()

        request_factory = RequestFactory()
        http_request = request_factory.get("/api/users/@me/")

        user = Mock(is_authenticated=True, is_active=True)
        org = Mock(spec=Organization)
        org.enforce_2fa = True
        user.organization = org
        http_request.user = user

        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(http_request)
        http_request.session.save()

        request = self.factory.get("/api/users/@me/")
        request._request = http_request

        with (
            patch("posthog.auth.is_impersonated_session", return_value=False),
            patch("posthog.auth.default_device", return_value=None),
            patch.object(auth, "enforce_csrf"),
        ):
            with self.assertRaises(PermissionDenied):
                auth.authenticate(request)

    def test_personal_api_key_authentication_bypasses_mfa(self):
        auth = PersonalAPIKeyAuthentication()
        request = self.factory.get("/api/users/@me/")

        result = auth.authenticate(request)
        self.assertIsNone(result)

    def test_temporary_token_authentication_bypasses_mfa(self):
        auth = TemporaryTokenAuthentication()
        request = self.factory.get("/api/users/@me/")

        result = auth.authenticate(request)
        self.assertIsNone(result)

    def test_project_secret_api_key_authentication_bypasses_mfa(self):
        auth = ProjectSecretAPIKeyAuthentication()
        request = self.factory.get("/api/users/@me/")

        result = auth.authenticate(request)
        self.assertIsNone(result)


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
