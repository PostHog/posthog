from posthog.test.base import APIBaseTest

from django.test import RequestFactory, override_settings

from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.auth import InternalAPIAuthentication


class TestInternalAPIAuth(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.authentication = InternalAPIAuthentication()

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_valid_secret_allows_access(self):
        request = Request(self.factory.get("/internal/endpoint", HTTP_X_INTERNAL_API_SECRET="test-secret-123"))
        user, auth = self.authentication.authenticate(request)
        self.assertTrue(user.is_authenticated)
        self.assertFalse(user.is_anonymous)
        self.assertIsNone(auth)

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_invalid_secret_denies_access(self):
        request = Request(self.factory.get("/internal/endpoint", HTTP_X_INTERNAL_API_SECRET="wrong-secret"))
        with self.assertRaises(AuthenticationFailed):
            self.authentication.authenticate(request)

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_missing_secret_denies_access(self):
        request = Request(self.factory.get("/internal/endpoint"))
        with self.assertRaises(AuthenticationFailed):
            self.authentication.authenticate(request)

    @override_settings(INTERNAL_API_SECRET="")
    def test_no_configured_secret_denies_access(self):
        request = Request(self.factory.get("/internal/endpoint", HTTP_X_INTERNAL_API_SECRET="any-secret"))
        with self.assertRaises(AuthenticationFailed):
            self.authentication.authenticate(request)

    def test_authenticate_header(self):
        request = self.factory.get("/internal/endpoint")
        self.assertEqual(self.authentication.authenticate_header(request), "InternalApiSecret")
