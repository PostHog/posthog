from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import INTERNAL_BOT_EMAIL_SUFFIX
from posthog.models.organization import Organization
from posthog.models.user import User


class TestOrganizationMembersForAccountAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.target_org = Organization.objects.create(name="Customer Org")

    def _url(self, organization_id: object) -> str:
        return f"/api/projects/{self.team.id}/organization_members/?organization_id={organization_id}"

    def _join(self, email: str, **kwargs) -> User:
        user = User.objects.create(email=email, **kwargs)
        user.join(organization=self.target_org)
        return user

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_returns_slim_members_of_target_org_when_staff_and_flag_enabled(self, _mock_flag):
        self._join("cust1@example.com", first_name="Ada", distinct_id="distinct-1")
        self._join("cust2@example.com", first_name="Grace", distinct_id="distinct-2")

        response = self.client.get(self._url(self.target_org.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertIn("count", body)
        self.assertEqual(body["count"], 2)
        results = body["results"]
        self.assertEqual({r["user"]["email"] for r in results}, {"cust1@example.com", "cust2@example.com"})
        self.assertEqual({r["user"]["distinct_id"] for r in results}, {"distinct-1", "distinct-2"})
        self.assertEqual(set(results[0].keys()), {"id", "user"})

    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_forbidden_when_flag_disabled(self, _mock_flag):
        response = self.client.get(self._url(self.target_org.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_forbidden_when_not_staff(self, _mock_flag):
        self.user.is_staff = False
        self.user.save()

        response = self.client.get(self._url(self.target_org.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @parameterized.expand(
        [
            ("missing", ""),
            ("invalid", "?organization_id=not-a-uuid"),
            ("empty", "?organization_id="),
        ]
    )
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_empty_results_for_bad_organization_id(self, _name, query_string, _mock_flag):
        response = self.client.get(f"/api/projects/{self.team.id}/organization_members/{query_string}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_paginates_results(self, _mock_flag):
        for index in range(7):
            self._join(f"member{index}@example.com", distinct_id=f"distinct-{index}")

        first_page = self.client.get(self._url(self.target_org.id) + "&limit=5&offset=0")
        self.assertEqual(first_page.status_code, status.HTTP_200_OK)
        first_body = first_page.json()
        self.assertEqual(first_body["count"], 7)
        self.assertEqual(len(first_body["results"]), 5)

        second_page = self.client.get(self._url(self.target_org.id) + "&limit=5&offset=5")
        self.assertEqual(second_page.status_code, status.HTTP_200_OK)
        self.assertEqual(len(second_page.json()["results"]), 2)

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_excludes_inactive_and_bot_users(self, _mock_flag):
        active = self._join("active@example.com", distinct_id="distinct-active")
        self._join("inactive@example.com", distinct_id="distinct-inactive", is_active=False)
        self._join(f"bot{INTERNAL_BOT_EMAIL_SUFFIX}", distinct_id="distinct-bot")

        response = self.client.get(self._url(self.target_org.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {r["user"]["email"] for r in response.json()["results"]}
        self.assertEqual(emails, {active.email})
