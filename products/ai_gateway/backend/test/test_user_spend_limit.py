from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.llm.gateway_internal_client import AIGatewayInternalError, AIGatewayNotConfigured, UserBudget
from posthog.models.user_gateway_node import gateway_user_node

CLIENT = "products.ai_gateway.backend.api.user_spend_limit"


class TestUserSpendLimit(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/ai_gateway/@me/spend_limit/{suffix}"

    @patch(f"{CLIENT}.get_user_budget", return_value=None)
    def test_reports_no_limit_but_enforceable(self, get_user_budget):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"limit_usd": None, "window_seconds": None, "enforced": True})
        get_user_budget.assert_called_once_with(self.team.id, gateway_user_node(self.user))

    @patch(
        f"{CLIENT}.get_user_budget",
        return_value=UserBudget(team_id=1, scope_value="u", limit_usd="500", window_seconds=2592000),
    )
    def test_reads_the_limit(self, _get_user_budget):
        response = self.client.get(self._url())
        self.assertEqual(response.json(), {"limit_usd": "500", "window_seconds": 2592000, "enforced": True})

    @patch(f"{CLIENT}.get_user_budget", side_effect=AIGatewayNotConfigured())
    def test_reads_as_unenforced_where_the_gateway_is_absent(self, _get_user_budget):
        response = self.client.get(self._url())
        self.assertEqual(response.json(), {"limit_usd": None, "window_seconds": None, "enforced": False})

    @patch(
        f"{CLIENT}.set_user_budget",
        return_value=UserBudget(team_id=1, scope_value="u", limit_usd="500", window_seconds=2592000),
    )
    def test_sets_the_limit_against_the_asserted_user_node(self, set_user_budget):
        response = self.client.post(self._url(), {"limit_usd": "500", "window_seconds": 2592000})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"limit_usd": "500", "window_seconds": 2592000, "enforced": True})
        # The scope value has to be the node a run's token pins and the desktop
        # asserts, or the gateway counts spend against a node this never
        # configured and the limit silently does nothing.
        set_user_budget.assert_called_once_with(self.team.id, gateway_user_node(self.user), "500.000000", 2592000)

    @patch(f"{CLIENT}.clear_user_budget", return_value=None)
    def test_clears_the_limit(self, clear_user_budget):
        response = self.client.delete(self._url("clear/"))
        self.assertEqual(response.json(), {"limit_usd": None, "window_seconds": None, "enforced": True})
        clear_user_budget.assert_called_once_with(self.team.id, gateway_user_node(self.user))

    def test_rejects_a_limit_the_gateway_would_refuse(self):
        for body in ({"limit_usd": "0", "window_seconds": 2592000}, {"limit_usd": "5", "window_seconds": 60}):
            with self.subTest(body=body):
                response = self.client.post(self._url(), body)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch(f"{CLIENT}.set_user_budget", side_effect=AIGatewayNotConfigured())
    def test_write_says_so_when_limits_are_unavailable(self, _set_user_budget):
        response = self.client.post(self._url(), {"limit_usd": "500", "window_seconds": 2592000})
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    @patch(f"{CLIENT}.set_user_budget", side_effect=AIGatewayInternalError("boom"))
    def test_write_surfaces_a_gateway_failure(self, _set_user_budget):
        response = self.client.post(self._url(), {"limit_usd": "500", "window_seconds": 2592000})
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
