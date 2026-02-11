from posthog.test.base import APIBaseTest

from django.http import JsonResponse
from django.test import RequestFactory, override_settings

from posthog.internal_api_auth import _check_internal_api_secret, require_internal_api_auth


@require_internal_api_auth
def mock_internal_view(request):
    return JsonResponse({"status": "ok"})


def mock_public_view(request):
    return JsonResponse({"status": "public"})


class TestInternalAPIAuth(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_valid_secret_allows_access(self):
        request = self.factory.get("/internal/endpoint")
        request.headers = {"X-Internal-Api-Secret": "test-secret-123"}
        response = mock_internal_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_invalid_secret_denies_access(self):
        request = self.factory.get("/internal/endpoint")
        request.headers = {"X-Internal-Api-Secret": "wrong-secret"}
        response = mock_internal_view(request)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Unauthorized", response.json()["error"])

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_missing_secret_denies_access(self):
        request = self.factory.get("/internal/endpoint")
        request.headers = {}
        response = mock_internal_view(request)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Unauthorized", response.json()["error"])

    @override_settings(INTERNAL_API_SECRET="")
    def test_no_configured_secret_denies_access(self):
        request = self.factory.get("/internal/endpoint")
        request.headers = {}
        response = mock_internal_view(request)
        self.assertEqual(response.status_code, 401)

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_check_internal_api_secret_helper(self):
        request = self.factory.get("/test")
        request.headers = {"X-Internal-Api-Secret": "test-secret-123"}
        self.assertTrue(_check_internal_api_secret(request))

        request.headers = {"X-Internal-Api-Secret": "wrong-secret"}
        self.assertFalse(_check_internal_api_secret(request))

        request.headers = {}
        self.assertFalse(_check_internal_api_secret(request))

    def test_public_view_not_affected(self):
        request = self.factory.get("/public/endpoint")
        request.headers = {}
        response = mock_public_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "public"})

    @override_settings(INTERNAL_API_SECRET="secret1")
    def test_timing_safe_comparison(self):
        request = self.factory.get("/test")

        # Test with similar length secrets (to ensure timing-safe comparison)
        request.headers = {"X-Internal-Api-Secret": "secret2"}
        self.assertFalse(_check_internal_api_secret(request))

        request.headers = {"X-Internal-Api-Secret": "secret1"}
        self.assertTrue(_check_internal_api_secret(request))
