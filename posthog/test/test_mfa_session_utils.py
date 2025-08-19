from unittest.mock import patch
from django.test import TestCase, RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.conf import settings

from posthog.mfa_session import (
    set_mfa_verified_in_session,
    is_mfa_verified_in_session,
    clear_mfa_session_flags,
    is_mfa_session_expired,
    MFA_VERIFIED_SESSION_KEY,
)


class TestMFASessionUtils(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.get("/")

        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(self.request)
        self.request.session.save()

    def test_set_mfa_verified_true(self):
        set_mfa_verified_in_session(self.request, True)

        self.assertTrue(self.request.session.get(MFA_VERIFIED_SESSION_KEY))

    def test_set_mfa_verified_false(self):
        self.request.session[MFA_VERIFIED_SESSION_KEY] = True

        set_mfa_verified_in_session(self.request, False)

        self.assertIsNone(self.request.session.get(MFA_VERIFIED_SESSION_KEY))

    def test_is_mfa_verified_in_session_with_valid_session(self):
        set_mfa_verified_in_session(self.request, True)
        self.request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = 1000.0

        with patch("time.time", return_value=1000.0 + settings.SESSION_COOKIE_AGE - 1):
            self.assertTrue(is_mfa_verified_in_session(self.request))

    def test_is_mfa_verified_in_session_with_expired_session(self):
        set_mfa_verified_in_session(self.request, True)
        self.request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = 1000.0

        with patch("time.time", return_value=1000.0 + settings.SESSION_COOKIE_AGE + 1):
            self.assertFalse(is_mfa_verified_in_session(self.request))

        self.assertIsNone(self.request.session.get(MFA_VERIFIED_SESSION_KEY))

    def test_is_mfa_verified_in_session_without_flag(self):
        self.assertFalse(is_mfa_verified_in_session(self.request))

    def test_is_mfa_verified_in_session_without_session_timestamp(self):
        self.request.session[MFA_VERIFIED_SESSION_KEY] = True
        self.assertFalse(is_mfa_verified_in_session(self.request))

    def test_clear_mfa_session_flags(self):
        self.request.session[MFA_VERIFIED_SESSION_KEY] = True

        clear_mfa_session_flags(self.request)

        self.assertIsNone(self.request.session.get(MFA_VERIFIED_SESSION_KEY))

    def test_clear_mfa_session_flags_when_empty(self):
        clear_mfa_session_flags(self.request)

        self.assertIsNone(self.request.session.get(MFA_VERIFIED_SESSION_KEY))

    def test_is_mfa_session_expired_without_session_created_timestamp(self):
        self.assertTrue(is_mfa_session_expired(self.request))

    def test_is_mfa_session_expired_with_valid_session(self):
        self.request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = 1000.0

        with patch("time.time", return_value=1000.0 + settings.SESSION_COOKIE_AGE - 1):
            self.assertFalse(is_mfa_session_expired(self.request))

    def test_is_mfa_session_expired_with_expired_session(self):
        self.request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = 1000.0

        with patch("time.time", return_value=1000.0 + settings.SESSION_COOKIE_AGE + 1):
            self.assertTrue(is_mfa_session_expired(self.request))
