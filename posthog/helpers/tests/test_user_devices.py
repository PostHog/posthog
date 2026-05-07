import uuid

from posthog.test.base import BaseTest

from django.test import RequestFactory

from parameterized import parameterized

from posthog.helpers.user_devices import (
    KNOWN_DEVICE_COOKIE,
    build_known_device_cookie_value,
    has_valid_known_device_cookie,
)
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
