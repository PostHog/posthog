import uuid

from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpResponse
from django.test import RequestFactory

from parameterized import parameterized

from posthog.helpers.user_devices import (
    KNOWN_DEVICE_COOKIE,
    build_known_device_cookie_value,
    has_valid_known_device_cookie,
)
from posthog.middleware import KnownLoginDeviceCookieMiddleware
from posthog.models import User


class TestHasValidKnownDeviceCookie(BaseTest):
    def _make_user(self) -> User:
        return User.objects.create(email=f"test-{uuid.uuid4()}@example.com", distinct_id=str(uuid.uuid4()))

    def _request_with_cookies(self, cookies: dict):
        request = RequestFactory().get("/")
        request.COOKIES.update(cookies)
        return request

    def test_returns_true_for_valid_signed_cookie(self):
        user = self._make_user()
        value = build_known_device_cookie_value(user)
        request = self._request_with_cookies({KNOWN_DEVICE_COOKIE.format(user_id=user.id): value})
        self.assertTrue(has_valid_known_device_cookie(request, user))

    def test_returns_false_when_cookie_absent(self):
        user = self._make_user()
        request = self._request_with_cookies({"sessionid": "abc"})
        self.assertFalse(has_valid_known_device_cookie(request, user))

    def test_returns_false_for_forged_unsigned_cookie(self):
        user = self._make_user()
        request = self._request_with_cookies({KNOWN_DEVICE_COOKIE.format(user_id=user.id): "1"})
        self.assertFalse(has_valid_known_device_cookie(request, user))

    def test_returns_false_for_different_user(self):
        user_a = self._make_user()
        user_b = self._make_user()
        value = build_known_device_cookie_value(user_a)
        # Place user_a's signed value under user_b's cookie name
        request = self._request_with_cookies({KNOWN_DEVICE_COOKIE.format(user_id=user_b.id): value})
        self.assertFalse(has_valid_known_device_cookie(request, user_b))

    def test_returns_false_after_password_change(self):
        user = self._make_user()
        value = build_known_device_cookie_value(user)
        user.set_password("new-password-that-changes-the-hash")
        user.save()
        request = self._request_with_cookies({KNOWN_DEVICE_COOKIE.format(user_id=user.id): value})
        self.assertFalse(has_valid_known_device_cookie(request, user))

    @parameterized.expand(
        [
            ("empty", ""),
            ("plain_text", "not-a-signed-payload"),
            ("colons", "::::"),
            ("short", "x:y"),
            ("garbage", "garbage:not-base62:zzz"),
        ]
    )
    def test_returns_false_for_malformed_cookie_without_raising(self, _name: str, value: str) -> None:
        # Garbage values must not propagate exceptions
        user = self._make_user()
        request = self._request_with_cookies({KNOWN_DEVICE_COOKIE.format(user_id=user.id): value})
        self.assertFalse(has_valid_known_device_cookie(request, user))


class TestKnownLoginDeviceCookieMiddleware(BaseTest):
    def _make_request(self, user=None):
        request = RequestFactory().get("/")
        request.session = SessionStore()
        if user is not None:
            request.user = user
            request.session["_auth_user_id"] = str(user.id)
        return request

    def _run_middleware(self, request):
        response = HttpResponse()
        middleware = KnownLoginDeviceCookieMiddleware(lambda r: response)
        return middleware(request)

    def _cookie_name(self) -> str:
        return KNOWN_DEVICE_COOKIE.format(user_id=self.user.id)

    def test_sets_cookie_for_authenticated_user(self):
        request = self._make_request(user=self.user)
        response = self._run_middleware(request)
        self.assertIn(self._cookie_name(), response.cookies)

    def test_does_not_set_cookie_when_session_has_no_auth_user_id(self):
        # API-key style requests: request.user is set by DRF auth, but no session login happened.
        request = RequestFactory().get("/")
        request.session = SessionStore()
        request.user = self.user
        response = self._run_middleware(request)
        self.assertNotIn(self._cookie_name(), response.cookies)

    def test_does_not_set_cookie_when_user_is_none(self):
        request = self._make_request()
        request.user = None
        response = self._run_middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.cookies), 0)

    def test_does_not_set_cookie_when_user_attr_missing(self):
        request = RequestFactory().get("/")
        request.session = SessionStore()
        if hasattr(request, "user"):
            del request.user
        response = self._run_middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.cookies), 0)

    def test_does_not_set_cookie_for_anonymous_user(self):
        from django.contrib.auth.models import AnonymousUser

        request = RequestFactory().get("/")
        request.session = SessionStore()
        request.user = AnonymousUser()
        response = self._run_middleware(request)
        self.assertEqual(len(response.cookies), 0)

    def test_does_not_set_cookie_for_non_user_types(self):
        # Things like ProjectSecretAPIKeyUser / InternalAPIUser set request.user directly to a
        # non-User type. The gate must reject these without crashing on missing attributes.
        fake_user = MagicMock(spec=[])
        fake_user.is_authenticated = True
        request = self._make_request()
        request.user = fake_user
        response = self._run_middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.cookies), 0)

    def test_does_not_set_cookie_when_session_attr_missing(self):
        request = RequestFactory().get("/")
        if hasattr(request, "session"):
            del request.session
        request.user = self.user
        response = self._run_middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.cookies), 0)
