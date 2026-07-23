from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings
from django.urls import include, path

from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import DefaultRouterPlusPlus
from posthog.decorators import disallow_if_impersonated


class ImpersonationTestViewSet(GenericViewSet):
    @action(methods=["GET", "POST"], detail=False)
    @disallow_if_impersonated()
    def blocked_action(self, request):
        return Response({"status": "success"})

    @action(methods=["GET", "POST"], detail=False)
    @disallow_if_impersonated(message="Custom error message.")
    def blocked_with_custom_message(self, request):
        return Response({"status": "success"})

    @action(methods=["GET", "POST"], detail=False)
    @disallow_if_impersonated(allowed_methods=["GET"])
    def partially_blocked(self, request):
        return Response({"status": "success", "method": request.method})


# A dedicated test URLconf instead of registering on the live application router: the live
# router's URL set is frozen the first time anything imports posthog.urls, so module-scope
# registrations only worked when this file happened to be collected before that — shard
# composition changes kept flipping the order. override_settings(ROOT_URLCONF=...) makes the
# routes exist exactly for these tests, in any order, and stops them leaking into the real
# URL space of every other test in the process.
_test_router = DefaultRouterPlusPlus()
_test_router.register(r"impersonation-test", ImpersonationTestViewSet, "impersonation-test")

urlpatterns = [path("api/", include(_test_router.urls))]


@override_settings(ROOT_URLCONF="posthog.test.test_decorators")
class TestDisallowIfImpersonatedDecorator(APIBaseTest):
    @patch("posthog.decorators.is_impersonated_session")
    def test_allows_non_impersonated_session(self, mock_is_impersonated):
        mock_is_impersonated.return_value = False

        response = self.client.get("/api/impersonation-test/blocked_action/")

        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch("posthog.decorators.is_impersonated_session")
    def test_blocks_impersonated_session(self, mock_is_impersonated):
        mock_is_impersonated.return_value = True

        response = self.client.get("/api/impersonation-test/blocked_action/")

        assert response.status_code == 403
        assert response.json()["detail"] == "Impersonated sessions cannot perform this action."

    @patch("posthog.decorators.is_impersonated_session")
    def test_custom_error_message(self, mock_is_impersonated):
        mock_is_impersonated.return_value = True

        response = self.client.get("/api/impersonation-test/blocked_with_custom_message/")

        assert response.status_code == 403
        assert response.json()["detail"] == "Custom error message."

    @patch("posthog.decorators.is_impersonated_session")
    def test_allowed_methods_get_is_allowed(self, mock_is_impersonated):
        mock_is_impersonated.return_value = True

        response = self.client.get("/api/impersonation-test/partially_blocked/")

        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert response.json()["method"] == "GET"

    @patch("posthog.decorators.is_impersonated_session")
    def test_allowed_methods_post_is_blocked(self, mock_is_impersonated):
        mock_is_impersonated.return_value = True

        response = self.client.post("/api/impersonation-test/partially_blocked/")

        assert response.status_code == 403
        assert response.json()["detail"] == "Impersonated sessions cannot perform this action."

    @patch("posthog.decorators.is_impersonated_session")
    def test_non_impersonated_can_use_all_methods(self, mock_is_impersonated):
        mock_is_impersonated.return_value = False

        get_response = self.client.get("/api/impersonation-test/partially_blocked/")
        post_response = self.client.post("/api/impersonation-test/partially_blocked/")

        assert get_response.status_code == 200
        assert post_response.status_code == 200
