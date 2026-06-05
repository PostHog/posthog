from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from posthog.admin.admins.llm_gateway_limits_admin import LLMGatewayLimitsViewSet
from posthog.llm.gateway_client import GatewayAdminError

USAGE_VIEW = LLMGatewayLimitsViewSet.as_view({"get": "retrieve"})
RESET_VIEW = LLMGatewayLimitsViewSet.as_view({"post": "reset"})


class TestLLMGatewayLimitsAdmin(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()

    def _make_staff(self):
        self.user.is_staff = True
        self.user.save()

    def test_usage_forbidden_for_non_staff(self):
        request = self.factory.get("/admin/api/llm-gateway-limits/100/")
        force_authenticate(request, user=self.user)
        response = USAGE_VIEW(request, user_id="100")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_reset_forbidden_for_non_staff(self):
        request = self.factory.post("/admin/api/llm-gateway-limits/100/reset/", {}, format="json")
        force_authenticate(request, user=self.user)
        response = RESET_VIEW(request, user_id="100")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("posthog.admin.admins.llm_gateway_limits_admin.get_posthog_code_usage")
    def test_staff_can_read_usage(self, mock_usage):
        self._make_staff()
        mock_usage.return_value = {"user_id": "100", "product": "posthog_code", "counters": []}

        request = self.factory.get("/admin/api/llm-gateway-limits/100/")
        force_authenticate(request, user=self.user)
        response = USAGE_VIEW(request, user_id="100")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["product"], "posthog_code")
        mock_usage.assert_called_once_with(100)

    @patch("posthog.admin.admins.llm_gateway_limits_admin.reset_posthog_code_usage")
    def test_staff_can_reset_with_flags(self, mock_reset):
        self._make_staff()
        mock_reset.return_value = {"user_id": "100", "total_keys": 3}

        request = self.factory.post(
            "/admin/api/llm-gateway-limits/100/reset/",
            {"reset_cost": True, "reset_request": True, "reset_product_total": True, "dry_run": False},
            format="json",
        )
        force_authenticate(request, user=self.user)
        response = RESET_VIEW(request, user_id="100")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_reset.assert_called_once_with(
            100, reset_cost=True, reset_request=True, reset_product_total=True, dry_run=False
        )

    @patch("posthog.admin.admins.llm_gateway_limits_admin.reset_posthog_code_usage")
    def test_reset_defaults_to_cost_only(self, mock_reset):
        self._make_staff()
        mock_reset.return_value = {"total_keys": 0}

        request = self.factory.post("/admin/api/llm-gateway-limits/100/reset/", {}, format="json")
        force_authenticate(request, user=self.user)
        response = RESET_VIEW(request, user_id="100")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_reset.assert_called_once_with(
            100, reset_cost=True, reset_request=False, reset_product_total=False, dry_run=False
        )

    @patch("posthog.admin.admins.llm_gateway_limits_admin.get_posthog_code_usage")
    def test_unconfigured_gateway_returns_503(self, mock_usage):
        self._make_staff()
        mock_usage.side_effect = GatewayAdminError("LLM_GATEWAY_ADMIN_SECRET is not configured")

        request = self.factory.get("/admin/api/llm-gateway-limits/100/")
        force_authenticate(request, user=self.user)
        response = USAGE_VIEW(request, user_id="100")

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
