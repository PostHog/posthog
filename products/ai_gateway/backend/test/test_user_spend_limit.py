from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from structlog.testing import capture_logs

from posthog.auth import IDJagAccessTokenAuthentication
from posthog.llm.gateway_internal_client import AIGatewayInternalError, AIGatewayNotConfigured, UserBudget
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import Organization
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

LOGIC = "products.ai_gateway.backend.logic"

BUDGET = UserBudget(limit_usd="500", window_seconds=2592000)
# The gateway answers a team's budget collection, so a 404 means it serves no
# budgets at all rather than that this person has none.
NO_BUDGET_SUPPORT = [
    ("not_configured", AIGatewayNotConfigured()),
    ("no_budgets_route", AIGatewayInternalError("not found", status_code=404)),
]


class TestUserSpendLimit(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/ai_gateway/@me/spend_limit/{suffix}"

    @property
    def _node(self) -> str:
        return self.user.distinct_id or f"user_{self.user.id}"

    @patch(f"{LOGIC}.get_user_budget", return_value=None)
    def test_reports_no_limit_where_limits_are_available(self, get_user_budget):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"limit_usd": None, "window_seconds": None, "available": True})
        get_user_budget.assert_called_once_with(self.team.id, self._node)

    @patch(f"{LOGIC}.get_user_budget", return_value=BUDGET)
    def test_reads_the_limit(self, _get_user_budget):
        response = self.client.get(self._url())
        self.assertEqual(response.json(), {"limit_usd": "500.000000", "window_seconds": 2592000, "available": True})

    @parameterized.expand(NO_BUDGET_SUPPORT)
    def test_reads_as_unavailable_where_the_gateway_holds_no_limits(self, _name, error):
        with patch(f"{LOGIC}.get_user_budget", side_effect=error):
            response = self.client.get(self._url())
        self.assertEqual(response.json(), {"limit_usd": None, "window_seconds": None, "available": False})

    @patch(f"{LOGIC}.set_user_budget", return_value=BUDGET)
    def test_sets_the_limit_against_the_asserted_user_node(self, set_user_budget):
        response = self.client.post(self._url(), {"limit_usd": "500", "window_seconds": 2592000})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"limit_usd": "500.000000", "window_seconds": 2592000, "available": True})
        # The scope value has to be the node a run's token pins and the desktop
        # asserts, or the gateway counts spend against a node this never
        # configured and the limit silently does nothing.
        set_user_budget.assert_called_once_with(self.team.id, self._node, "500.000000", 2592000)

    @patch(f"{LOGIC}.clear_user_budget", return_value=None)
    def test_clears_the_limit(self, clear_user_budget):
        response = self.client.delete(self._url("clear/"))
        self.assertEqual(response.json(), {"limit_usd": None, "window_seconds": None, "available": True})
        clear_user_budget.assert_called_once_with(self.team.id, self._node)

    @parameterized.expand(NO_BUDGET_SUPPORT)
    def test_clear_says_unavailable_where_the_gateway_holds_no_limits(self, _name, error):
        # A 404 on DELETE means the gateway serves no budgets route, not that the
        # user had a limit to clear. Clear must fail like write does, not claim a
        # limit was removed. Read reports `available: false` for the same gateway;
        # clear must not disagree with it.
        with patch(f"{LOGIC}.clear_user_budget", side_effect=error):
            response = self.client.delete(self._url("clear/"))
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    @parameterized.expand(
        [
            ("limit_below_the_floor", {"limit_usd": "0", "window_seconds": 2592000}),
            ("window_below_an_hour", {"limit_usd": "5", "window_seconds": 60}),
        ]
    )
    def test_rejects_a_limit_the_gateway_would_refuse(self, _name, body):
        response = self.client.post(self._url(), body)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(NO_BUDGET_SUPPORT)
    def test_write_says_so_when_limits_are_unavailable(self, _name, error):
        with patch(f"{LOGIC}.set_user_budget", side_effect=error):
            response = self.client.post(self._url(), {"limit_usd": "500", "window_seconds": 2592000})
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    @parameterized.expand(
        [
            ("gateway_down", 500, "spend_limits_unavailable"),
            ("request_refused", 422, "spend_limits_rejected"),
        ]
    )
    def test_write_surfaces_a_gateway_failure_with_its_kind(self, _name, gateway_status, expected_code):
        with patch(f"{LOGIC}.set_user_budget", side_effect=AIGatewayInternalError("boom", status_code=gateway_status)):
            response = self.client.post(self._url(), {"limit_usd": "500", "window_seconds": 2592000})
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.json()["code"], expected_code)

    def test_rejects_a_personal_api_key_scoped_to_another_project(self):
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Scoped key",
            user=self.user,
            secure_value=hash_key_value(token),
            scopes=["*"],
            scoped_teams=[self.team.id + 1],
            scoped_organizations=[],
        )

        response = self.client.get(self._url(), headers={"authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_rejects_a_personal_api_key_where_the_organization_bans_them(self):
        self.organization.available_product_features = [
            {"key": "organization_security_settings", "name": "Organization security settings"}
        ]
        self.organization.members_can_use_personal_api_keys = False
        self.organization.save()
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Banned key", user=self.user, secure_value=hash_key_value(token), scopes=["*"]
        )

        response = self.client.get(self._url(), headers={"authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch(f"{LOGIC}.get_user_budget", return_value=None)
    def test_writes_need_the_ai_gateway_write_scope(self, _get_user_budget):
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Read key", user=self.user, secure_value=hash_key_value(token), scopes=["ai_gateway:read"]
        )
        headers = {"authorization": f"Bearer {token}"}

        self.assertEqual(self.client.get(self._url(), headers=headers).status_code, status.HTTP_200_OK)
        response = self.client.post(self._url(), {"limit_usd": "500", "window_seconds": 2592000}, headers=headers)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_rejects_an_oauth_token_scoped_to_another_organization(self):
        other_organization = Organization.objects.create(name="Other organization")
        application = OAuthApplication.objects.create(
            name="Test OAuth app",
            client_id="test_client_id",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            user=self.user,
        )
        access_token = OAuthAccessToken.objects.create(
            application=application,
            user=self.user,
            token="pha_test_oauth_token",
            scope="*",
            expires=timezone.now() + timedelta(hours=1),
            scoped_organizations=[str(other_organization.id)],
        )

        response = self.client.get(self._url(), headers={"authorization": f"Bearer {access_token.token}"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_rejects_an_id_jag_token_scoped_to_another_organization(self):
        other_organization = Organization.objects.create(name="Other organization")

        def authenticate(authenticator: IDJagAccessTokenAuthentication, _request: object) -> tuple[object, None]:
            authenticator.scopes = ["*"]
            authenticator.organization_id = str(other_organization.id)
            return self.user, None

        with patch.object(IDJagAccessTokenAuthentication, "authenticate", autospec=True, side_effect=authenticate):
            response = self.client.get(self._url(), headers={"authorization": "Bearer id-jag-test-token"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @parameterized.expand(
        [
            ("read", "get_user_budget", lambda test: test.client.get(test._url())),
            (
                "write",
                "set_user_budget",
                lambda test: test.client.post(test._url(), {"limit_usd": "500", "window_seconds": 2592000}),
            ),
            ("clear", "clear_user_budget", lambda test: test.client.delete(test._url("clear/"))),
        ]
    )
    def test_gateway_failures_are_logged_with_operation_and_team(self, operation, helper_name, request):
        with patch(f"{LOGIC}.{helper_name}", side_effect=AIGatewayInternalError("boom", status_code=500)):
            with capture_logs() as logs:
                response = request(self)

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        failure_logs = [log for log in logs if log.get("event") == "ai_gateway_user_spend_limit_gateway_error"]
        self.assertEqual(len(failure_logs), 1)
        self.assertEqual(failure_logs[0]["operation"], operation)
        self.assertEqual(failure_logs[0]["team_id"], self.team.id)
        self.assertEqual(failure_logs[0]["error"], "boom")
