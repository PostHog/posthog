import time
import datetime

import pytest
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient, APIRequestFactory

from posthog.auth import (
    PersonalAPIKeyAuthentication,
    ProjectSecretAPIKeyAuthentication,
    SessionAuthentication,
    TemporaryTokenAuthentication,
)
from posthog.helpers.two_factor_session import (
    TWO_FACTOR_ENFORCEMENT_FROM_DATE,
    clear_two_factor_session_flags,
    is_two_factor_session_expired,
    is_two_factor_verified_in_session,
    set_two_factor_verified_in_session,
)
from posthog.models import Organization, User


class TestTwoFactorSessionUtils(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _create_request(self):
        request = self.factory.get("/test/")
        middleware = SessionMiddleware(lambda request: HttpResponse())
        middleware.process_request(request)
        request.session.save()
        return request

    def test_set_two_factor_verified_true(self):
        request = self._create_request()
        set_two_factor_verified_in_session(request, verified=True)
        self.assertTrue(request.session.get("two_factor_verified"))

    def test_set_two_factor_verified_false(self):
        request = self._create_request()
        set_two_factor_verified_in_session(request, verified=False)
        self.assertFalse(request.session.get("two_factor_verified"))

    def test_is_two_factor_verified_in_session_with_valid_session(self):
        request = self._create_request()
        request.session["two_factor_verified"] = True
        request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = time.time()
        self.assertTrue(is_two_factor_verified_in_session(request))

    def test_is_two_factor_verified_in_session_without_flag(self):
        request = self._create_request()
        after_date = time.mktime((TWO_FACTOR_ENFORCEMENT_FROM_DATE + datetime.timedelta(days=1)).timetuple())
        request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = after_date
        self.assertFalse(is_two_factor_verified_in_session(request))

    @patch("time.time")
    def test_is_two_factor_verified_in_session_with_expired_session(self, mock_time):
        request = self._create_request()
        request.session["two_factor_verified"] = True

        session_created_time = time.mktime((TWO_FACTOR_ENFORCEMENT_FROM_DATE + datetime.timedelta(days=1)).timetuple())
        mock_current_time = session_created_time + settings.SESSION_COOKIE_AGE + 1
        mock_time.return_value = mock_current_time

        request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = session_created_time
        self.assertFalse(is_two_factor_verified_in_session(request))

    def test_clear_two_factor_session_flags(self):
        request = self._create_request()
        request.session["two_factor_verified"] = True
        clear_two_factor_session_flags(request)
        self.assertFalse(request.session.get("two_factor_verified", False))

    def test_clear_two_factor_session_flags_when_empty(self):
        request = self._create_request()
        clear_two_factor_session_flags(request)
        self.assertFalse(request.session.get("two_factor_verified", False))

    def test_is_two_factor_session_expired_with_valid_session(self):
        request = self._create_request()
        request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = time.time()
        self.assertFalse(is_two_factor_session_expired(request))

    def test_is_two_factor_session_expired_with_expired_session(self):
        request = self._create_request()
        request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = time.time() - (15 * 24 * 60 * 60)
        self.assertTrue(is_two_factor_session_expired(request))

    def test_is_two_factor_session_expired_without_session_created_timestamp(self):
        request = self._create_request()
        self.assertTrue(is_two_factor_session_expired(request))


class TestSessionAuthenticationTwoFactor(TestCase):
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

        middleware = SessionMiddleware(lambda request: HttpResponse())
        middleware.process_request(http_request)
        http_request.session.save()

        request = self.factory.get(path)
        request._request = http_request
        return request

    def _set_session_after_enforcement_date(self, request):
        after_date = time.mktime((TWO_FACTOR_ENFORCEMENT_FROM_DATE + datetime.timedelta(days=1)).timetuple())
        request._request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = after_date
        request._request.session.save()

    def _set_session_before_enforcement_date(self, request):
        before_date = time.mktime((TWO_FACTOR_ENFORCEMENT_FROM_DATE - datetime.timedelta(days=1)).timetuple())
        request._request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = before_date
        request._request.session.save()

    @patch("posthog.helpers.two_factor_session.default_device")
    @patch("posthog.helpers.two_factor_session.is_impersonated_session")
    def test_authentication_skips_impersonated_sessions(self, mock_is_impersonated, mock_default_device):
        mock_is_impersonated.return_value = True
        mock_default_device.return_value = Mock()
        request = self._create_drf_request()

        with patch.object(self.user, "organization", self.organization), patch.object(self.auth, "enforce_csrf"):
            result = self.auth.authenticate(request)
            self.assertEqual(result, (self.user, None))

    @patch("posthog.helpers.two_factor_session.is_impersonated_session")
    def test_authentication_allows_when_organization_not_enforce_2fa(self, mock_is_impersonated):
        mock_is_impersonated.return_value = False
        org_no_2fa = Mock(spec=Organization)
        org_no_2fa.enforce_2fa = False
        request = self._create_drf_request()

        with patch.object(self.user, "organization", org_no_2fa), patch.object(self.auth, "enforce_csrf"):
            result = self.auth.authenticate(request)
            self.assertEqual(result, (self.user, None))

    @patch("posthog.helpers.two_factor_session.default_device")
    @patch("posthog.helpers.two_factor_session.is_impersonated_session")
    def test_authentication_raises_permission_denied_when_no_2fa_device(
        self, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = None
        request = self._create_drf_request()
        self._set_session_after_enforcement_date(request)

        with patch.object(self.user, "organization", self.organization), patch.object(self.auth, "enforce_csrf"):
            with self.assertRaises(PermissionDenied) as cm:
                self.auth.authenticate(request)
            self.assertEqual(str(cm.exception.detail), "2FA setup required")

    @patch("posthog.helpers.two_factor_session.default_device")
    @patch("posthog.helpers.two_factor_session.is_impersonated_session")
    @patch("posthog.helpers.two_factor_session.is_two_factor_verified_in_session")
    def test_authentication_raises_permission_denied_when_session_not_verified(
        self, mock_is_two_factor_verified, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = Mock()
        mock_is_two_factor_verified.return_value = False
        request = self._create_drf_request()
        self._set_session_after_enforcement_date(request)

        with patch.object(self.user, "organization", self.organization), patch.object(self.auth, "enforce_csrf"):
            with self.assertRaises(PermissionDenied) as cm:
                self.auth.authenticate(request)
            self.assertEqual(str(cm.exception.detail), "2FA verification required")

    @patch("posthog.helpers.two_factor_session.default_device")
    @patch("posthog.helpers.two_factor_session.is_impersonated_session")
    @patch("posthog.helpers.two_factor_session.is_two_factor_verified_in_session")
    def test_authentication_succeeds_when_fully_verified(
        self, mock_is_two_factor_verified, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = Mock()
        mock_is_two_factor_verified.return_value = True
        request = self._create_drf_request()

        with patch.object(self.user, "organization", self.organization), patch.object(self.auth, "enforce_csrf"):
            result = self.auth.authenticate(request)
            self.assertEqual(result, (self.user, None))

    @patch("posthog.helpers.two_factor_session.is_domain_sso_enforced", return_value=True)
    @patch("posthog.helpers.two_factor_session.is_two_factor_enforcement_in_effect", return_value=True)
    def test_authentication_bypasses_two_factor_when_sso_enforced(self, _mock_enforcement, _mock_sso):
        request = self._create_drf_request()
        with patch.object(self.user, "organization", self.organization), patch.object(self.auth, "enforce_csrf"):
            result = self.auth.authenticate(request)
            self.assertEqual(result, (self.user, None))

    @patch("posthog.helpers.two_factor_session.default_device")
    @patch("posthog.helpers.two_factor_session.is_impersonated_session")
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
                self.assertEqual(result, (self.user, None))

    @patch("posthog.helpers.two_factor_session.default_device")
    @patch("posthog.helpers.two_factor_session.is_impersonated_session")
    def test_authentication_enforces_two_factor_on_non_whitelisted_paths(
        self, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = None

        non_whitelisted_paths = [
            "/api/projects/1/insights/",
            "/dashboard/123",
            "/insights/abc123",
        ]

        for path in non_whitelisted_paths:
            request = self._create_drf_request(path=path)
            self._set_session_after_enforcement_date(request)

            with patch.object(self.user, "organization", self.organization), patch.object(self.auth, "enforce_csrf"):
                with self.assertRaises(PermissionDenied) as cm:
                    self.auth.authenticate(request)
                self.assertEqual(str(cm.exception.detail), "2FA setup required")

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

    @patch("posthog.helpers.two_factor_session.default_device")
    @patch("posthog.helpers.two_factor_session.is_impersonated_session")
    def test_authentication_bypasses_two_factor_for_sessions_before_enforcement_date(
        self, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = None
        request = self._create_drf_request()
        self._set_session_before_enforcement_date(request)

        with patch.object(self.user, "organization", self.organization), patch.object(self.auth, "enforce_csrf"):
            result = self.auth.authenticate(request)
            self.assertEqual(result, (self.user, None))

    @patch("posthog.helpers.two_factor_session.default_device")
    @patch("posthog.helpers.two_factor_session.is_impersonated_session")
    def test_authentication_enforces_two_factor_for_sessions_after_enforcement_date(
        self, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = None
        request = self._create_drf_request()
        self._set_session_after_enforcement_date(request)

        with patch.object(self.user, "organization", self.organization), patch.object(self.auth, "enforce_csrf"):
            with self.assertRaises(PermissionDenied) as cm:
                self.auth.authenticate(request)
            self.assertEqual(str(cm.exception.detail), "2FA setup required")

    @patch("posthog.helpers.two_factor_session.default_device")
    @patch("posthog.helpers.two_factor_session.is_impersonated_session")
    def test_authentication_bypasses_two_factor_for_sessions_without_timestamp(
        self, mock_is_impersonated, mock_default_device
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = None
        request = self._create_drf_request()

        if settings.SESSION_COOKIE_CREATED_AT_KEY in request._request.session:
            del request._request.session[settings.SESSION_COOKIE_CREATED_AT_KEY]
        request._request.session.save()

        with patch.object(self.user, "organization", self.organization), patch.object(self.auth, "enforce_csrf"):
            result = self.auth.authenticate(request)
            self.assertEqual(result, (self.user, None))


class TestTwoFactorImpersonationIntegration(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.auth = SessionAuthentication()

    def _create_drf_request(self, path="/test/", user=None):
        request_factory = RequestFactory()
        http_request = request_factory.get(path)
        http_request.user = user if user is not None else Mock(is_authenticated=True, is_active=True)

        middleware = SessionMiddleware(lambda request: HttpResponse())
        middleware.process_request(http_request)
        http_request.session.save()

        request = self.factory.get(path)
        request._request = http_request
        return request

    def _set_session_after_enforcement_date(self, request):
        after_date = time.mktime((TWO_FACTOR_ENFORCEMENT_FROM_DATE + datetime.timedelta(days=1)).timetuple())
        request._request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = after_date
        request._request.session.save()

    @patch("posthog.helpers.two_factor_session.is_impersonated_session")
    def test_session_authentication_bypasses_two_factor_for_impersonated_sessions(self, mock_is_impersonated):
        mock_is_impersonated.return_value = True
        user = Mock(is_authenticated=True, is_active=True)
        org = Mock(spec=Organization)
        org.enforce_2fa = True
        user.organization = org

        request = self._create_drf_request(user=user)
        self._set_session_after_enforcement_date(request)

        with patch.object(self.auth, "enforce_csrf"):
            result = self.auth.authenticate(request)
            self.assertEqual(result, (user, None))

    @patch("posthog.helpers.two_factor_session.is_impersonated_session")
    @patch("posthog.helpers.two_factor_session.default_device")
    def test_session_authentication_enforces_two_factor_for_non_impersonated_sessions(
        self, mock_default_device, mock_is_impersonated
    ):
        mock_is_impersonated.return_value = False
        mock_default_device.return_value = None

        user = Mock(is_authenticated=True, is_active=True)
        org = Mock(spec=Organization)
        org.enforce_2fa = True
        user.organization = org

        request = self._create_drf_request(user=user)
        self._set_session_after_enforcement_date(request)

        with patch.object(self.auth, "enforce_csrf"):
            with self.assertRaises(PermissionDenied) as cm:
                self.auth.authenticate(request)
            self.assertEqual(str(cm.exception.detail), "2FA setup required")


class TestAPIAuthenticationTwoFactorBypass(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def _set_session_after_enforcement_date(self, http_request):
        after_date = time.mktime((TWO_FACTOR_ENFORCEMENT_FROM_DATE + datetime.timedelta(days=1)).timetuple())
        http_request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = after_date
        http_request.session.save()

    def test_session_authentication_enforces_two_factor(self):
        auth = SessionAuthentication()

        request_factory = RequestFactory()
        http_request = request_factory.get("/api/organizations/")

        user = Mock(is_authenticated=True, is_active=True)
        org = Mock(spec=Organization)
        org.enforce_2fa = True
        user.organization = org
        http_request.user = user

        middleware = SessionMiddleware(lambda request: HttpResponse())
        middleware.process_request(http_request)
        http_request.session.save()
        self._set_session_after_enforcement_date(http_request)

        request = self.factory.get("/api/organizations/")
        request._request = http_request

        with (
            patch("posthog.helpers.two_factor_session.is_impersonated_session", return_value=False),
            patch("posthog.helpers.two_factor_session.default_device", return_value=None),
            patch.object(auth, "enforce_csrf"),
        ):
            with self.assertRaises(PermissionDenied):
                auth.authenticate(request)

    def test_personal_api_key_authentication_bypasses_two_factor(self):
        auth = PersonalAPIKeyAuthentication()
        request = self.factory.get("/api/users/@me/")

        result = auth.authenticate(request)
        self.assertIsNone(result)

    def test_temporary_token_authentication_bypasses_two_factor(self):
        auth = TemporaryTokenAuthentication()
        request = self.factory.get("/api/users/@me/")

        result = auth.authenticate(request)
        self.assertIsNone(result)

    def test_project_secret_api_key_authentication_bypasses_two_factor(self):
        auth = ProjectSecretAPIKeyAuthentication()
        request = self.factory.get("/api/users/@me/")

        result = auth.authenticate(request)
        self.assertIsNone(result)

    def test_sso_authentication_backend_bypasses_two_factor(self):
        """Integration test: SSO authentication backends should bypass 2FA enforcement"""
        auth = SessionAuthentication()

        request_factory = RequestFactory()
        http_request = request_factory.get("/api/organizations/")

        user = Mock(is_authenticated=True, is_active=True, email="test@example.com")
        org = Mock(spec=Organization)
        org.enforce_2fa = True
        user.organization = org
        http_request.user = user

        middleware = SessionMiddleware(lambda request: HttpResponse())
        middleware.process_request(http_request)
        self._set_session_after_enforcement_date(http_request)

        request = self.factory.get("/api/organizations/")
        request._request = http_request

        with (
            patch("posthog.helpers.two_factor_session.is_impersonated_session", return_value=False),
            patch("posthog.helpers.two_factor_session.default_device", return_value=None),
            patch("posthog.helpers.two_factor_session.is_sso_authentication_backend", return_value=True),
            patch.object(auth, "enforce_csrf"),
        ):
            result = auth.authenticate(request)
            self.assertEqual(result, (user, None))


class TestUserTwoFactorSessionIntegration(TestCase):
    database = ["default", "replica"]

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
    def test_two_factor_validate_sets_two_factor_session_flag(self, mock_send_email, mock_totp_form):
        mock_form_instance = mock_totp_form.return_value
        mock_form_instance.is_valid.return_value = True

        session = self.client.session
        session["django_two_factor-hex"] = "1234567890abcdef1234"
        session.save()

        factory = RequestFactory()
        request = factory.post("/api/users/@me/two_factor_validate/", {"token": "123456"})

        middleware = SessionMiddleware(lambda request: HttpResponse())
        middleware.process_request(request)

        self.assertFalse(is_two_factor_verified_in_session(request))

        response = self.client.post(f"/api/users/@me/two_factor_validate/", {"token": "123456"})
        self.assertEqual(response.status_code, 200)

        test_request = factory.get("/")
        middleware.process_request(test_request)
        test_request.session = self.client.session

        self.assertTrue(is_two_factor_verified_in_session(test_request))

        mock_totp_form.assert_called_once_with("1234567890abcdef1234", self.user, data={"token": "123456"})
        mock_form_instance.save.assert_called_once()
        mock_send_email.delay.assert_called_once_with(self.user.id)

    @pytest.mark.no_mock_two_factor_sso_enforcement_check
    def test_doesnt_break_swagger_schema(self):
        """Test that schema generation works without session middleware errors"""
        response = self.client.get("/api/schema/")
        self.assertEqual(response.status_code, 200)
