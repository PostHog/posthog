from posthog.test.base import APIBaseTest

from django.test import RequestFactory, override_settings

from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.internal_api_auth import InternalAPIAuthentication, _check_internal_api_secret


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

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_check_internal_api_secret_helper(self):
        request = self.factory.get("/test")
        request.headers = {"X-Internal-Api-Secret": "test-secret-123"}
        self.assertTrue(_check_internal_api_secret(request))

        request.headers = {"X-Internal-Api-Secret": "wrong-secret"}
        self.assertFalse(_check_internal_api_secret(request))

        request.headers = {}
        self.assertFalse(_check_internal_api_secret(request))

    def test_authenticate_header(self):
        request = self.factory.get("/internal/endpoint")
        self.assertEqual(self.authentication.authenticate_header(request), "InternalApiSecret")
